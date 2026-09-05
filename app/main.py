"""FastAPI entrypoint: POST /chat.

Run with:
    uvicorn app.main:app --reload
"""

from fastapi import FastAPI

from app.assistant import decide_and_respond
from app.schemas import ChatRequest, ChatResponse

app = FastAPI(title="SaaS Customer Support Assistant", version="1.0.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    return decide_and_respond(request)
