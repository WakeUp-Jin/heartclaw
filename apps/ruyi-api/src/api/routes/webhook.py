from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request, Response

from utils.logger import logger

router = APIRouter()

_event_handler_ref: Any = None


def set_event_handler(handler: Any) -> None:
    global _event_handler_ref
    _event_handler_ref = handler


@router.post("/api/webhook/feishu")
async def feishu_webhook(request: Request):
    """Feishu event callback endpoint (production Webhook mode)."""
    body = await request.json()

    # URL verification challenge
    if "challenge" in body:
        return {"challenge": body["challenge"]}

    event_type = body.get("header", {}).get("event_type", "")
    logger.info("Webhook event: %s", event_type)

    return {"code": 0, "msg": "ok"}
