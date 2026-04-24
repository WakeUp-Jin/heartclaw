from __future__ import annotations

import json
from typing import Any, Callable, Awaitable

from utils.logger import logger

_seen_message_ids: set[str] = set()
MAX_SEEN = 1000


def is_duplicate(message_id: str) -> bool:
    if message_id in _seen_message_ids:
        return True
    _seen_message_ids.add(message_id)
    if len(_seen_message_ids) > MAX_SEEN:
        to_remove = list(_seen_message_ids)[:MAX_SEEN // 2]
        for mid in to_remove:
            _seen_message_ids.discard(mid)
    return False


def parse_message_event(data: Any) -> dict[str, Any] | None:
    """Extract essential fields from im.message.receive_v1 event."""
    try:
        event = data.event
        msg = event.message
        sender = event.sender

        if msg.chat_type != "p2p":
            logger.debug("Ignoring non-p2p message: chat_type=%s", msg.chat_type)
            return None

        if msg.message_type != "text":
            logger.debug("Ignoring non-text message: type=%s", msg.message_type)
            return None

        message_id = msg.message_id
        if is_duplicate(message_id):
            logger.debug("Duplicate message ignored: %s", message_id)
            return None

        content_raw = msg.content
        try:
            text = json.loads(content_raw).get("text", "")
        except (json.JSONDecodeError, TypeError):
            text = str(content_raw)

        return {
            "text": text,
            "chat_id": msg.chat_id,
            "message_id": message_id,
            "open_id": sender.sender_id.open_id if sender and sender.sender_id else "",
        }
    except Exception as e:
        logger.error("Failed to parse message event: %s", e)
        return None
