# Cleanomatics — RAG + Tool-Using Support Assistant

A small FastAPI customer-support assistant for a SaaS company. It answers
product/policy questions from a local knowledge base, looks up order status
via a mock tool, and refuses to answer (rather than guess) when neither
source has verified information.

This repo covers both tasks of the assessment:

- **Task 1** — working code, in `app/` (this README).
- **Task 2** — design document, in [`TASK2_DESIGN.md`](TASK2_DESIGN.md).

## Quickstart

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate    # macOS/Linux
pip install -r requirements.txt

uvicorn app.main:app --reload
```

Then POST to `http://127.0.0.1:8000/chat`:

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d "{\"message\": \"What is your refund policy?\"}"
```

Interactive docs: `http://127.0.0.1:8000/docs`.

## Running the required test cases

```bash
python -m tests.test_cases
```

This runs all 6 required test cases in-process (no server needed) and
prints each request/response pair — see [Sample requests/responses](#sample-requestsresponses)
below for captured output.

## Architecture

```
app/
  main.py            FastAPI app, POST /chat
  schemas.py          Pydantic request/response models
  knowledge_base.py    FAQ documents + TF-IDF retrieval
  tools.py             Mock get_order_status(order_id) tool
  assistant.py         Orchestration: routing, grounding, answer composition
tests/
  test_cases.py         The 6 required test cases
TASK2_DESIGN.md         Task 2 answers (workflow redesign, idempotency, etc.)
```

### Request flow (`app/assistant.py: decide_and_respond`)

1. **Validate input.** Empty/whitespace-only messages get a direct
   clarification response instead of being sent through retrieval/tooling.
2. **Extract order intent.** An order id is read from `order_id` if
   supplied, else parsed out of the message text via regex
   (`ORD-<alphanumeric>`); order-related keywords (e.g. "order",
   "shipment", "track") without an id are recognized as "wants order info
   but didn't give an id" for the missing-id test case.
3. **Retrieve.** The message is always run through TF-IDF + cosine-
   similarity retrieval against the knowledge base (top-3), regardless of
   whether an order intent was also detected — this is what lets one
   message combine a policy question and an order lookup (test case 3).
4. **Apply the relevance threshold.** Only the top document is used, and
   only if its score clears `RELEVANCE_THRESHOLD` (see below) — otherwise
   the knowledge base is treated as having nothing relevant to say.
5. **Call the tool, if needed.** `get_order_status(order_id)` is called
   with the extracted id. Its three outcomes (success / not found / tool
   error) are handled explicitly and produce distinct, honest responses —
   none of them fabricate a status.
6. **Compose the answer strictly from verified pieces.** The final answer
   is built by templating in the literal retrieved document content and/or
   literal tool result — never free-form generation — so the "never invent
   order status or policy information" requirement is a structural
   guarantee, not a prompting hope. See [Design note: why no live LLM
   call](#design-note-why-no-live-llm-call) below.
7. Return JSON: `answer`, `source` (which path produced the answer),
   `confidence` (the top retrieval score, where applicable), and
   `evidence` (every retrieved doc + score, every tool call + its
   result/error) so the caller can audit exactly what the answer is based
   on.

### Retrieval: why TF-IDF instead of an embeddings API

`app/knowledge_base.py` uses `TfidfVectorizer` + cosine similarity
(scikit-learn) rather than a hosted embeddings API. For a KB this size
(7 short FAQ entries) TF-IDF retrieval quality is close to embeddings for
this task, and it keeps the whole assistant runnable fully offline with no
API key — important for the required test cases to be deterministic and
reproducible. The retrieval interface (`retrieve(query, top_k)`) is the
only place that would change to swap in real embeddings + a vector DB for
a larger, more semantically varied knowledge base.

### Choosing the relevance threshold

`RELEVANCE_THRESHOLD = 0.2` in `app/knowledge_base.py`. TF-IDF cosine
similarity for short FAQ-style documents like these empirically clusters
into two bands: on-topic queries score roughly 0.3-0.7+ against their
matching document (they share the document's distinctive vocabulary),
while off-topic queries score under ~0.15 (only incidental word overlap,
e.g. shared stopword-adjacent terms). 0.2 sits in the gap between those
two clusters with a margin on both sides. In production this would be
tuned against a labeled set of (query, expected-doc) pairs rather than
picked by eye, and revisited whenever the KB's documents or typical query
phrasing change materially.

### Design note: why no live LLM call

Routing (retrieve vs. tool vs. both vs. neither) and answer phrasing are
done with explicit rules/templates rather than an LLM call. This was a
deliberate choice, not a shortcut:

- The task explicitly requires the assistant never invent order status or
  policy information. Templating the answer directly from retrieved-doc
  text and tool JSON makes that a structural property of the code, rather
  than something a prompt merely asks an LLM to respect.
- It keeps the required test cases (including the simulated tool failure
  and the missing-order-id case) deterministic and runnable with zero API
  keys or network access, which matters for grading/reproducibility.

`decide_and_respond` in `app/assistant.py` is the single seam where this
would be replaced with a real LLM call: an Anthropic/OpenAI tool-use loop,
using the system instruction drafted in `TASK2_DESIGN.md` (Q7), would
receive the same `retrieved_docs`/`tool_result` payloads assembled here and
would be constrained to phrase an answer only from them — the tool call
itself would remain a deterministic function call made by application
code, not something the model is trusted to fabricate the result of.

## Requirements coverage

| Requirement | Where |
|---|---|
| POST /chat endpoint | `app/main.py` |
| >=5 KB documents | `app/knowledge_base.py` (7 documents) |
| Embeddings/vector search or lightweight alternative | TF-IDF + cosine similarity |
| One tool with mock data | `app/tools.py: get_order_status` |
| Decides retrieve vs. tool | `app/assistant.py: decide_and_respond` |
| No invented order status/policy | Answers are templated only from retrieved/tool content |
| JSON with answer + evidence/tool used | `ChatResponse` (`answer`, `source`, `evidence`) |
| Handles missing order id, irrelevant Qs, empty input, tool failure | See flow steps 1, 2, 5 above |
| Confidence/relevance rule | `RELEVANCE_THRESHOLD`, explained above |

## Sample requests/responses

Captured from `python -m tests.test_cases` (see that file for the exact
payloads). Actual scores may shift slightly if the knowledge base is
edited.

### 1. Knowledge-base question

Request:
```json
{"message": "What is your refund policy?"}
```
Response:
```json
{
  "answer": "We offer full refunds within 14 days of purchase if you are not satisfied. Refunds are processed to the original payment method within 5-7 business days.",
  "source": "knowledge_base",
  "confidence": 0.348,
  "evidence": {
    "retrieved_docs": [
      {"doc_id": "refund_policy", "title": "Refund Policy", "score": 0.348},
      {"doc_id": "subscription_cancellation", "title": "Cancelling a Subscription", "score": 0.0},
      {"doc_id": "password_reset", "title": "Resetting Your Password", "score": 0.0}
    ],
    "tool_calls": []
  }
}
```

### 2. Order-status question requiring the tool

Request:
```json
{"message": "What's the status of my order?", "order_id": "ORD-1001"}
```
Response:
```json
{
  "answer": "Order ORD-1001 is currently 'Shipped' (items: Widget Pro x2; expected 2026-09-08).",
  "source": "tool",
  "confidence": 1.0,
  "evidence": {
    "retrieved_docs": [ "..." ],
    "tool_calls": [
      {
        "name": "get_order_status",
        "arguments": {"order_id": "ORD-1001"},
        "result": {"order_id": "ORD-1001", "status": "Shipped", "eta": "2026-09-08", "items": ["Widget Pro x2"]},
        "error": null
      }
    ]
  }
}
```

### 3. Combined policy + order lookup

Request:
```json
{"message": "Can I get a refund, and also what's the status of order ORD-1002?"}
```
Response:
```json
{
  "answer": "We offer full refunds within 14 days of purchase if you are not satisfied. Refunds are processed to the original payment method within 5-7 business days. Order ORD-1002 is currently 'Processing' (items: Starter Kit x1; expected 2026-09-10).",
  "source": "knowledge_base+tool",
  "confidence": 0.2461,
  "evidence": { "...": "retrieved doc + tool_call for ORD-1002" }
}
```

### 4. Question outside the knowledge base

Request:
```json
{"message": "What's the weather like today?"}
```
Response:
```json
{
  "answer": "I don't have enough verified information to answer that confidently. Could you rephrase, or contact support for anything outside product/policy FAQs?",
  "source": "cannot_verify",
  "confidence": 0.0,
  "evidence": { "retrieved_docs": [ "all below threshold" ], "tool_calls": [] }
}
```

### 5. Invalid/missing order ID

Request:
```json
{"message": "What's the status of my order?"}
```
Response:
```json
{
  "answer": "I can look up your order, but I need an order ID (e.g. ORD-1001) to do so.",
  "source": "clarification_needed",
  "confidence": 0.0,
  "evidence": {"retrieved_docs": ["..."], "tool_calls": []}
}
```

### 6. Simulated tool failure

Request:
```json
{"message": "Where is my order?", "order_id": "ORD-FAIL"}
```
Response:
```json
{
  "answer": "I'm unable to reach the order-status service right now, so I can't verify this order. Please try again shortly.",
  "source": "tool_error",
  "confidence": 0.0,
  "evidence": {
    "retrieved_docs": ["..."],
    "tool_calls": [
      {"name": "get_order_status", "arguments": {"order_id": "ORD-FAIL"}, "result": null, "error": "order-status API is currently unavailable"}
    ]
  }
}
```

`ORD-FAIL` is a reserved id in `app/tools.py` used to deterministically
simulate an upstream failure without needing to mock HTTP internals.

## Assumptions and trade-offs

- No real LLM call is made (see [Design note](#design-note-why-no-live-llm-call)
  above) — prioritized grounding guarantees and offline reproducibility
  over natural-language answer variety.
- TF-IDF retrieval, not embeddings — appropriate at this KB size; documented
  as the first thing to change if the KB grows or gets more semantically
  diverse.
- Order id format assumed to be `ORD-<alphanumeric>`; the regex would need
  adjusting for a real system's actual id format.
- Idempotency/retry/timeout handling for the order API (raised by the
  scenario in Task 2) is designed but not implemented in Task 1's mock
  tool, since the tool call here is synchronous, in-process, and
  effectively free — that infrastructure only matters once it's a real
  network call, which is where Task 2 addresses it in detail.
