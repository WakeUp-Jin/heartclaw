"""飞书 IM 消息工具 - 合并发送/回复/历史为单一 feishu_message 工具"""

from __future__ import annotations

import json
from typing import Any

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
    ListMessageRequest,
)

from core.tool.feishu.client import FeishuClient
from utils import logger


feishu_message_def = {
    "name": "feishu_message",
    "description": (
        "飞书消息操作：发送消息、回复消息、获取历史消息。"
        "action=send 需要 receive_id/receive_id_type/msg_type/content；"
        "action=reply 需要 message_id/msg_type/content；"
        "action=get_history 需要 container_id。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["send", "reply", "get_history"],
                "description": "操作类型：send=发送消息, reply=回复消息, get_history=获取历史消息",
            },
            "receive_id": {"type": "string", "description": "接收者 ID（send 时必填）"},
            "receive_id_type": {
                "type": "string",
                "enum": ["open_id", "user_id", "union_id", "email", "chat_id"],
                "description": "接收者 ID 类型（send 时必填）",
            },
            "message_id": {"type": "string", "description": "要回复的消息 ID（reply 时必填）"},
            "msg_type": {
                "type": "string",
                "enum": ["text", "post", "interactive"],
                "description": "消息类型（send/reply 时必填）",
            },
            "content": {
                "type": "string",
                "description": "消息内容 JSON 字符串，例如文本消息: {\"text\":\"hello\"}（send/reply 时必填）",
            },
            "container_id": {"type": "string", "description": "会话 ID / chat_id（get_history 时必填）"},
            "start_time": {"type": "string", "description": "起始时间戳（秒）（get_history 可选）"},
            "end_time": {"type": "string", "description": "结束时间戳（秒）（get_history 可选）"},
            "page_size": {
                "type": "integer",
                "description": "每页数量（get_history 可选，默认 20，最大 50）",
            },
        },
        "required": ["action"],
    },
}


async def _handle_send(client: FeishuClient, args: dict) -> str:
    receive_id = args.get("receive_id") or ""
    receive_id_type = args.get("receive_id_type") or "chat_id"
    msg_type = args.get("msg_type") or "text"
    content = args.get("content") or ""

    request = (
        CreateMessageRequest.builder()
        .receive_id_type(receive_id_type)
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(receive_id)
            .msg_type(msg_type)
            .content(content)
            .build()
        )
        .build()
    )

    resp = client.client.im.v1.message.create(request)
    client.increment_api_count()

    err = client.check_response(resp, "feishu_message.send")
    if err:
        return client.to_json(err)

    return client.to_json({"message_id": resp.data.message_id})


async def _handle_reply(client: FeishuClient, args: dict) -> str:
    message_id = args.get("message_id") or ""
    msg_type = args.get("msg_type") or "text"
    content = args.get("content") or ""

    request = (
        ReplyMessageRequest.builder()
        .message_id(message_id)
        .request_body(
            ReplyMessageRequestBody.builder()
            .msg_type(msg_type)
            .content(content)
            .build()
        )
        .build()
    )

    resp = client.client.im.v1.message.reply(request)
    client.increment_api_count()

    err = client.check_response(resp, "feishu_message.reply")
    if err:
        return client.to_json(err)

    return client.to_json({"message_id": resp.data.message_id})


async def _handle_get_history(client: FeishuClient, args: dict) -> str:
    container_id = args.get("container_id") or ""
    start_time = args.get("start_time")
    end_time = args.get("end_time")
    page_size = args.get("page_size", 20)

    builder = (
        ListMessageRequest.builder()
        .container_id_type("chat_id")
        .container_id(container_id)
        .page_size(min(page_size, 50))
    )
    if start_time is not None:
        builder = builder.start_time(str(start_time))
    if end_time is not None:
        builder = builder.end_time(str(end_time))

    request = builder.build()

    resp = client.client.im.v1.message.list(request)
    client.increment_api_count()

    err = client.check_response(resp, "feishu_message.get_history")
    if err:
        return client.to_json(err)

    messages = []
    for item in (resp.data.items or []):
        msg = {
            "sender_id": item.sender.id if item.sender else None,
            "msg_type": item.msg_type,
            "content": item.body.content if item.body else None,
            "create_time": item.create_time,
        }
        messages.append(msg)

    return client.to_json({"messages": messages})


_ACTION_MAP = {
    "send": _handle_send,
    "reply": _handle_reply,
    "get_history": _handle_get_history,
}


async def feishu_message_handler(client: FeishuClient, args: dict) -> str:
    action = args.get("action", "")
    handler = _ACTION_MAP.get(action)
    if handler is None:
        return json.dumps({"error": f"Unknown action: {action}"})
    return await handler(client, args)
