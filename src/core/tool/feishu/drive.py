"""飞书云空间工具 - 合并文件列表/创建文件夹/文件信息/根目录为单一 feishu_drive 工具"""

from __future__ import annotations

import json
from typing import Any

import lark_oapi as lark
from lark_oapi.api.drive.v1 import *

from core.tool.feishu.client import FeishuClient
from utils import logger


feishu_drive_def = {
    "name": "feishu_drive",
    "description": (
        "飞书云空间操作：列出文件、创建文件夹、获取文件信息、获取根目录。"
        "action=list_files 可选 folder_token/page_size/page_token；"
        "action=create_folder 需要 name；"
        "action=get_info 需要 file_token；"
        "action=get_root 无需额外参数。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list_files", "create_folder", "get_info", "get_root"],
                "description": "操作类型",
            },
            "folder_token": {"type": "string", "description": "文件夹 token（list_files/create_folder 可选）"},
            "page_size": {"type": "integer", "description": "每页数量（list_files 可选，默认 50，最大 200）"},
            "page_token": {"type": "string", "description": "分页标记（list_files 可选）"},
            "name": {"type": "string", "description": "文件夹名称（create_folder 时必填）"},
            "file_token": {"type": "string", "description": "文件或文件夹的 token（get_info 时必填）"},
        },
        "required": ["action"],
    },
}


def _doc_type_from_token(token: str) -> str:
    if not token:
        return "doc"
    t = token.lower()
    if t.startswith("fld"):
        return "folder"
    if t.startswith("dox") or t.startswith("doc"):
        return "docx"
    if t.startswith("sht"):
        return "sheet"
    if t.startswith("bas"):
        return "bitable"
    return "doc"


async def _handle_list_files(client: FeishuClient, args: dict) -> str:
    folder_token = args.get("folder_token") or ""
    page_size = args.get("page_size", 50)
    page_token = args.get("page_token") or ""

    req_builder = ListFileRequest.builder()
    if folder_token:
        req_builder.folder_token(folder_token)
    req_builder.page_size(min(page_size, 200))
    if page_token:
        req_builder.page_token(page_token)
    request = req_builder.build()

    resp = await client.client.drive.v1.file.alist(request)
    client.increment_api_count()
    err = client.check_response(resp, "feishu_drive.list_files")
    if err:
        return client.to_json(err)

    body = resp.data
    if not body:
        return client.to_json({"files": [], "next_page_token": "", "has_more": False})

    files = []
    for f in (body.files or []):
        files.append({
            "name": getattr(f, "name", None) or "",
            "type": getattr(f, "type", None) or "",
            "token": getattr(f, "token", None) or "",
        })

    return client.to_json({
        "files": files,
        "next_page_token": getattr(body, "next_page_token", None) or "",
        "has_more": getattr(body, "has_more", False) or False,
    })


async def _handle_create_folder(client: FeishuClient, args: dict) -> str:
    name = args.get("name") or ""
    folder_token = args.get("folder_token") or ""

    body_builder = CreateFolderFileRequestBody.builder().name(name)
    if folder_token:
        body_builder.folder_token(folder_token)
    body = body_builder.build()

    request = CreateFolderFileRequest.builder().request_body(body).build()

    resp = await client.client.drive.v1.file.acreate_folder(request)
    client.increment_api_count()
    err = client.check_response(resp, "feishu_drive.create_folder")
    if err:
        return client.to_json(err)

    resp_body = resp.data
    token = getattr(resp_body, "token", None) or ""
    url = getattr(resp_body, "url", None) or ""
    return client.to_json({"folder_token": token, "url": url})


async def _handle_get_info(client: FeishuClient, args: dict) -> str:
    file_token = args.get("file_token") or ""
    if not file_token:
        return client.to_json({"error": "file_token is required"})

    doc_type = _doc_type_from_token(file_token)
    request_doc = RequestDoc.builder().doc_token(file_token).doc_type(doc_type).build()
    meta_req = MetaRequest.builder().request_docs([request_doc]).with_url(True).build()
    request = BatchQueryMetaRequest.builder().request_body(meta_req).build()

    resp = await client.client.drive.v1.meta.abatch_query(request)
    client.increment_api_count()
    err = client.check_response(resp, "feishu_drive.get_info")
    if err:
        return client.to_json(err)

    body = resp.data
    metas = getattr(body, "metas", None) or []
    if not metas:
        return client.to_json({"error": "File not found or no meta returned"})

    meta = metas[0]
    return client.to_json({
        "name": getattr(meta, "title", None) or "",
        "type": getattr(meta, "doc_type", None) or "",
        "url": getattr(meta, "url", None) or "",
    })


async def _handle_get_root(client: FeishuClient, args: dict) -> str:
    return client.to_json({
        "root_folder_token": "",
        "hint": "Use feishu_drive with action=list_files and empty folder_token to list root directory",
    })


_ACTION_MAP = {
    "list_files": _handle_list_files,
    "create_folder": _handle_create_folder,
    "get_info": _handle_get_info,
    "get_root": _handle_get_root,
}


async def feishu_drive_handler(client: FeishuClient, args: dict) -> str:
    action = args.get("action", "")
    handler = _ACTION_MAP.get(action)
    if handler is None:
        return json.dumps({"error": f"Unknown action: {action}"})
    return await handler(client, args)
