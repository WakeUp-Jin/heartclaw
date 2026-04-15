from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from core.agent.context_vars import current_chat_id

router = APIRouter()

_agent_ref: Any = None
_agent_lock: asyncio.Lock | None = None


def set_agent(agent: Any) -> None:
    global _agent_ref
    _agent_ref = agent


def set_agent_lock(lock: asyncio.Lock) -> None:
    global _agent_lock
    _agent_lock = lock


class ChatRequest(BaseModel):
    text: str
    chat_id: str = "debug"
    open_id: str = "debug"


class ChatResponse(BaseModel):
    reply: str


@router.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if _agent_ref is None:
        return ChatResponse(reply="Agent not initialized")

    if _agent_lock:
        async with _agent_lock:
            current_chat_id.set(req.chat_id)
            reply = await _agent_ref.run(req.text, req.chat_id, req.open_id)
    else:
        current_chat_id.set(req.chat_id)
        reply = await _agent_ref.run(req.text, req.chat_id, req.open_id)

    return ChatResponse(reply=reply)
