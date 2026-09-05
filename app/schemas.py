"""Pydantic request/response models for the /chat endpoint."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., description="The customer's question, in natural language.")
    customer_id: Optional[str] = Field(None, description="Optional customer identifier.")
    order_id: Optional[str] = Field(
        None, description="Optional order id, if the customer already knows it."
    )


class RetrievedDoc(BaseModel):
    doc_id: str
    title: str
    score: float


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any]
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class Evidence(BaseModel):
    retrieved_docs: list[RetrievedDoc] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)


SourceType = Literal[
    "knowledge_base",
    "tool",
    "knowledge_base+tool",
    "cannot_verify",
    "clarification_needed",
    "tool_error",
    "tool_not_found",
]


class ChatResponse(BaseModel):
    answer: str
    source: SourceType
    confidence: float
    evidence: Evidence
