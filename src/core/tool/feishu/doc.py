"""飞书云文档工具 - 合并创建/读取/更新/信息为单一 feishu_doc 工具"""

from __future__ import annotations

import json
from typing import Any

import lark_oapi as lark
from lark_oapi.api.docx.v1 import (
    Block,
    CreateDocumentBlockChildrenRequestBody,
    CreateDocumentBlockChildrenRequest,
    CreateDocumentRequestBody,
    CreateDocumentRequest,
    GetDocumentRequest,
    ListDocumentBlockRequest,
    RawContentDocumentRequest,
    Text,
    TextElement,
    TextRun,
)

from core.tool.feishu.client import FeishuClient
from utils import logger

_BLOCK_TYPE_MAP = {
    "paragraph": 2,
    "heading1": 3,
    "heading2": 4,
    "heading3": 5,
    "bullet": 12,
    "ordered": 13,
    "code": 14,
}


feishu_doc_def = {
    "name": "feishu_doc",
    "description": (
        "飞书云文档操作：创建/读取/更新文档、获取文档信息。"
        "action=create 需要 title；"
        "action=read 需要 document_id（返回纯文本）；"
        "action=read_blocks 需要 document_id（返回块结构）；"
        "action=update 需要 document_id/block_id/content_blocks；"
        "action=get_info 需要 document_id。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "read", "read_blocks", "update", "get_info"],
                "description": "操作类型",
            },
            "document_id": {"type": "string", "description": "文档 ID（read/read_blocks/update/get_info 时必填）"},
            "title": {"type": "string", "description": "文档标题（create 时必填）"},
            "folder_token": {"type": "string", "description": "目标文件夹 token（create 可选）"},
            "block_id": {
                "type": "string",
                "description": "父块 ID，传 document_id 表示追加到文档末尾（update 时必填）",
            },
            "content_blocks": {
                "type": "array",
                "description": "要追加的内容块列表（update 时必填）",
                "items": {
                    "type": "object",
                    "properties": {
                        "block_type": {
                            "type": "string",
                            "enum": ["paragraph", "heading1", "heading2", "heading3", "bullet", "ordered", "code"],
                        },
                        "content": {"type": "string", "description": "块的文本内容"},
                    },
                    "required": ["block_type", "content"],
                },
            },
            "page_size": {"type": "integer", "description": "每页块数量（read_blocks 可选，默认 500）"},
        },
        "required": ["action"],
    },
}


# ---------------------------------------------------------------------------
# Internal handlers
# ---------------------------------------------------------------------------

async def _handle_create(client: FeishuClient, args: dict) -> str:
    title = args.get("title") or ""
    folder_token = args.get("folder_token") or ""

    body_builder = CreateDocumentRequestBody.builder().title(title)
    if folder_token:
        body_builder = body_builder.folder_token(folder_token)

    request = CreateDocumentRequest.builder().request_body(body_builder.build()).build()

    resp = await client.client.docx.v1.document.acreate(request)
    client.increment_api_count()

    err = client.check_response(resp, "feishu_doc.create")
    if err:
        return client.to_json(err)

    doc = resp.data.document
    document_id = doc.document_id
    url = f"https://feishu.cn/docx/{document_id}"

    return client.to_json({"document_id": document_id, "title": title, "url": url})


async def _handle_read(client: FeishuClient, args: dict) -> str:
    document_id = args.get("document_id") or ""

    request = RawContentDocumentRequest.builder().document_id(document_id).build()

    resp = await client.client.docx.v1.document.araw_content(request)
    client.increment_api_count()

    err = client.check_response(resp, "feishu_doc.read")
    if err:
        return client.to_json(err)

    content = resp.data.content or ""
    return client.to_json({"content": content})


def _simplify_block(block: Block) -> dict:
    result: dict[str, Any] = {
        "block_id": block.block_id or "",
        "block_type": block.block_type or 0,
    }

    text_obj = None
    for attr in ("text", "heading1", "heading2", "heading3", "bullet", "ordered", "code"):
        text_obj = getattr(block, attr, None)
        if text_obj is not None:
            break

    if text_obj and text_obj.elements:
        parts = []
        for elem in text_obj.elements:
            if elem.text_run and elem.text_run.content:
                parts.append(elem.text_run.content)
        result["content"] = "".join(parts)
    else:
        result["content"] = ""

    return result


async def _handle_read_blocks(client: FeishuClient, args: dict) -> str:
    document_id = args.get("document_id") or ""
    page_size = args.get("page_size", 500)

    request = (
        ListDocumentBlockRequest.builder()
        .document_id(document_id)
        .page_size(page_size)
        .build()
    )

    resp = await client.client.docx.v1.document_block.alist(request)
    client.increment_api_count()

    err = client.check_response(resp, "feishu_doc.read_blocks")
    if err:
        return client.to_json(err)

    items = resp.data.items or []
    blocks = [_simplify_block(b) for b in items]

    return client.to_json({
        "blocks": blocks,
        "page_token": resp.data.page_token or "",
        "has_more": resp.data.has_more or False,
    })


def _build_text_with_content(content: str) -> Text:
    text_run = TextRun.builder().content(content or " ").build()
    text_element = TextElement.builder().text_run(text_run).build()
    return Text.builder().elements([text_element]).build()


def _content_block_to_block(item: dict) -> Block:
    block_type_str = item.get("block_type", "paragraph")
    content = item.get("content", "") or " "

    type_num = _BLOCK_TYPE_MAP.get(block_type_str, 2)
    text_obj = _build_text_with_content(content)

    builder = Block.builder().block_type(type_num)

    attr_map = {
        "paragraph": "text",
        "heading1": "heading1",
        "heading2": "heading2",
        "heading3": "heading3",
        "bullet": "bullet",
        "ordered": "ordered",
        "code": "code",
    }
    attr_name = attr_map.get(block_type_str, "text")
    builder = getattr(builder, attr_name)(text_obj)

    return builder.build()


async def _handle_update(client: FeishuClient, args: dict) -> str:
    document_id = args.get("document_id") or ""
    block_id = args.get("block_id") or ""
    content_blocks = args.get("content_blocks", [])

    if not content_blocks:
        return client.to_json({"error": "content_blocks 不能为空"})

    children = [_content_block_to_block(cb) for cb in content_blocks]

    body = (
        CreateDocumentBlockChildrenRequestBody.builder()
        .children(children)
        .index(-1)
        .build()
    )

    request = (
        CreateDocumentBlockChildrenRequest.builder()
        .document_id(document_id)
        .block_id(block_id)
        .request_body(body)
        .build()
    )

    resp = await client.client.docx.v1.document_block_children.acreate(request)
    client.increment_api_count()

    err = client.check_response(resp, "feishu_doc.update")
    if err:
        return client.to_json(err)

    count = len(resp.data.children) if resp.data and resp.data.children else len(children)

    return client.to_json({"success": True, "count": count})


async def _handle_get_info(client: FeishuClient, args: dict) -> str:
    document_id = args.get("document_id") or ""

    request = GetDocumentRequest.builder().document_id(document_id).build()

    resp = await client.client.docx.v1.document.aget(request)
    client.increment_api_count()

    err = client.check_response(resp, "feishu_doc.get_info")
    if err:
        return client.to_json(err)

    doc = resp.data.document

    result: dict[str, Any] = {
        "document_id": doc.document_id,
        "title": doc.title or "",
        "revision_id": doc.revision_id,
    }

    if hasattr(doc, "create_time") and doc.create_time is not None:
        result["create_time"] = doc.create_time
    if hasattr(doc, "update_time") and doc.update_time is not None:
        result["update_time"] = doc.update_time

    return client.to_json(result)


# ---------------------------------------------------------------------------
# Unified router
# ---------------------------------------------------------------------------

_ACTION_MAP = {
    "create": _handle_create,
    "read": _handle_read,
    "read_blocks": _handle_read_blocks,
    "update": _handle_update,
    "get_info": _handle_get_info,
}


async def feishu_doc_handler(client: FeishuClient, args: dict) -> str:
    action = args.get("action", "")
    handler = _ACTION_MAP.get(action)
    if handler is None:
        return json.dumps({"error": f"Unknown action: {action}"})
    return await handler(client, args)
