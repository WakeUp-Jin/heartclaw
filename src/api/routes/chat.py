from __future__ import annotations

from typing import Any, TYPE_CHECKING

from fastapi import APIRouter
from pydantic import BaseModel

from core.agent.context_vars import current_chat_id
from core.queue.types import QueueMessage, MessagePriority

if TYPE_CHECKING:
    from core.queue.message_queue import MessageQueue

router = APIRouter()

_agent_ref: Any = None
_queue_ref: MessageQueue | None = None


def set_agent(agent: Any) -> None:
    global _agent_ref
    _agent_ref = agent


def set_message_queue(queue: MessageQueue) -> None:
    global _queue_ref
    _queue_ref = queue


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

    current_chat_id.set(req.chat_id)

    if _queue_ref is not None:
        msg = QueueMessage(
            priority=MessagePriority.USER,
            mode="user",
            content=req.text,
            chat_id=req.chat_id,
            open_id=req.open_id,
            source_channel="api",
        )
        future = await _queue_ref.enqueue(msg)
        reply = await future
    else:
        reply = await _agent_ref.run(req.text, req.chat_id, req.open_id)

    return ChatResponse(reply=reply)
