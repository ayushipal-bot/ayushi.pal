"""Agent orchestration: decide whether to retrieve, call the order-status
tool, both, or neither — then compose an answer strictly from what was
retrieved/returned.

Reasoning layer
1. Grounding: the task requires that the assistant never invent order
   status or policy content. Building the final answer only by templating
   in the literal retrieved-doc text and literal tool response makes that
   guarantee structural instead of hoping a prompt is obeyed.
2. Determinism: the required test cases (missing order id, tool failure,
   irrelevant question, ...) need to be reliably reproducible without an
   API key or model non-determinism.

`decide_and_respond` is the single seam where this would be swapped for a
real LLM call (e.g. an Anthropic/OpenAI tool-use loop with the system
prompt from Task 2, question 7): the LLM would still only be allowed to
phrase an answer from the same retrieved_docs/tool_result payloads
assembled below, never to invent facts of its own.
"""

import re

from app.knowledge_base import RELEVANCE_THRESHOLD, retrieve
from app.schemas import ChatRequest, ChatResponse, Evidence, RetrievedDoc, ToolCall
from app.tools import OrderNotFoundError, ToolExecutionError, get_order_status

_ORDER_ID_PATTERN = re.compile(r"\bORD-[A-Za-z0-9]{3,10}\b", re.IGNORECASE)
_ORDER_KEYWORDS = {
    "order",
    "orders",
    "shipment",
    "shipped",
    "shipping",
    "delivery",
    "delivered",
    "track",
    "tracking",
    "package",
    "parcel",
}


def _extract_order_id(request: ChatRequest) -> str | None:
    if request.order_id:
        return request.order_id.strip()
    match = _ORDER_ID_PATTERN.search(request.message)
    return match.group(0).upper() if match else None


def _mentions_order(message: str) -> bool:
    words = set(re.findall(r"[a-z]+", message.lower()))
    return bool(words & _ORDER_KEYWORDS)


def decide_and_respond(request: ChatRequest) -> ChatResponse:
    message = request.message.strip()
    if not message:
        return ChatResponse(
            answer="Please enter a question so I can help.",
            source="cannot_verify",
            confidence=0.0,
            evidence=Evidence(),
        )

    order_id = _extract_order_id(request)
    order_intent = order_id is not None or _mentions_order(message)

    
    ranked = retrieve(message)
    retrieved_docs = [
        RetrievedDoc(doc_id=doc.doc_id, title=doc.title, score=round(float(score), 4))
        for doc, score in ranked
    ]
    best_score = retrieved_docs[0].score if retrieved_docs else 0.0
    kb_relevant = best_score >= RELEVANCE_THRESHOLD

    tool_calls: list[ToolCall] = []
    order_sentence: str | None = None
    tool_outcome: str | None = None  # "ok" | "not_found" | "error" | "missing_id" | None

    if order_intent:
        if order_id is None:
            tool_outcome = "missing_id"
        else:
            try:
                result = get_order_status(order_id)
                tool_calls.append(
                    ToolCall(name="get_order_status", arguments={"order_id": order_id}, result=result)
                )
                order_sentence = (
                    f"Order {result['order_id']} is currently '{result['status']}' "
                    f"(items: {', '.join(result['items'])}; expected {result['eta']})."
                )
                tool_outcome = "ok"
            except OrderNotFoundError as exc:
                tool_calls.append(
                    ToolCall(name="get_order_status", arguments={"order_id": order_id}, error=str(exc))
                )
                tool_outcome = "not_found"
            except ToolExecutionError as exc:
                tool_calls.append(
                    ToolCall(name="get_order_status", arguments={"order_id": order_id}, error=str(exc))
                )
                tool_outcome = "error"

    kb_sentence = None
    if kb_relevant:
        top_doc = ranked[0][0]
        kb_sentence = top_doc.content

    evidence = Evidence(retrieved_docs=retrieved_docs, tool_calls=tool_calls)

    # --- Compose the final answer strictly from verified pieces above ---
    if order_sentence and kb_sentence:
        return ChatResponse(
            answer=f"{kb_sentence} {order_sentence}",
            source="knowledge_base+tool",
            confidence=round(best_score, 4),
            evidence=evidence,
        )
    if order_sentence:
        return ChatResponse(
            answer=order_sentence,
            source="tool",
            confidence=1.0,
            evidence=evidence,
        )
    if tool_outcome == "missing_id":
        return ChatResponse(
            answer="I can look up your order, but I need an order ID (e.g. ORD-1001) to do so.",
            source="clarification_needed",
            confidence=0.0,
            evidence=evidence,
        )
    if tool_outcome == "not_found":
        return ChatResponse(
            answer=f"I couldn't find an order with id '{order_id}'. Please double-check the order ID.",
            source="tool_not_found",
            confidence=0.0,
            evidence=evidence,
        )
    if tool_outcome == "error":
        return ChatResponse(
            answer=(
                "I'm unable to reach the order-status service right now, so I can't verify "
                "this order. Please try again shortly."
            ),
            source="tool_error",
            confidence=0.0,
            evidence=evidence,
        )
    if kb_sentence:
        return ChatResponse(
            answer=kb_sentence,
            source="knowledge_base",
            confidence=round(best_score, 4),
            evidence=evidence,
        )

    return ChatResponse(
        answer=(
            "I don't have enough verified information to answer that confidently. "
            "Could you rephrase, or contact support for anything outside product/policy FAQs?"
        ),
        source="cannot_verify",
        confidence=round(best_score, 4),
        evidence=evidence,
    )
