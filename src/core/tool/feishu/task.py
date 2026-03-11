"""飞书任务工具 - 合并创建/查询/更新任务和创建任务列表为单一 feishu_task 工具"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import lark_oapi as lark
from lark_oapi.api.task.v2 import *

from core.tool.feishu.client import FeishuClient
from utils import logger


feishu_task_def = {
    "name": "feishu_task",
    "description": (
        "飞书任务操作：创建任务、查询任务列表、更新任务、创建任务列表。"
        "action=create 需要 summary；"
        "action=list 可选 completed/page_size/page_token；"
        "action=update 需要 task_id；"
        "action=create_tasklist 需要 name。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "update", "create_tasklist"],
                "description": "操作类型",
            },
            "summary": {"type": "string", "description": "任务标题（create/update 时使用）"},
            "description": {"type": "string", "description": "任务详细描述（create/update 可选）"},
            "due": {"type": "string", "description": "截止时间 ISO 8601 格式（create/update 可选）"},
            "members": {
                "type": "array",
                "items": {"type": "string"},
                "description": "执行者 user_id 列表（create 可选）",
            },
            "tasklist_id": {"type": "string", "description": "任务列表 ID（create 可选）"},
            "task_id": {"type": "string", "description": "任务 ID（update 时必填）"},
            "completed": {"type": "boolean", "description": "筛选完成/未完成（list 可选），或标记已完成（update 可选）"},
            "page_size": {"type": "integer", "description": "每页数量（list 可选，默认 50）"},
            "page_token": {"type": "string", "description": "分页标记（list 可选）"},
            "name": {"type": "string", "description": "任务列表名称（create_tasklist 时必填）"},
        },
        "required": ["action"],
    },
}


def _parse_iso_to_timestamp(iso_str: str | None) -> int | None:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return None


async def _handle_create(client: FeishuClient, args: dict) -> str:
    summary = args.get("summary") or ""
    description = args.get("description")
    due_str = args.get("due")
    members_raw = args.get("members") or []
    tasklist_id = args.get("tasklist_id")

    task_builder = InputTask.builder().summary(summary)
    if description:
        task_builder.description(description)
    if due_str:
        ts = _parse_iso_to_timestamp(due_str)
        if ts:
            task_builder.due(Due.builder().timestamp(ts).is_all_day(False).build())
    if members_raw:
        task_builder.members([
            Member.builder().id(uid).type("user").role("assignee").build()
            for uid in members_raw
        ])
    if tasklist_id:
        task_builder.tasklists([
            TaskInTasklistInfo.builder().tasklist_guid(tasklist_id).build(),
        ])

    body = task_builder.build()
    request = CreateTaskRequest.builder().request_body(body).build()

    resp = await client.client.task.v2.task.acreate(request)
    client.increment_api_count()
    err = client.check_response(resp, "feishu_task.create")
    if err:
        return client.to_json(err)

    task_obj = getattr(resp.data, "task", None)
    task_id = getattr(task_obj, "guid", None) or ""
    return client.to_json({"task_id": task_id})


async def _handle_list(client: FeishuClient, args: dict) -> str:
    completed = args.get("completed")
    page_size = args.get("page_size", 50)
    page_token = args.get("page_token") or ""

    req_builder = ListTaskRequest.builder().page_size(page_size)
    if completed is not None:
        req_builder.completed(completed)
    if page_token:
        req_builder.page_token(page_token)
    request = req_builder.build()

    resp = await client.client.task.v2.task.alist(request)
    client.increment_api_count()
    err = client.check_response(resp, "feishu_task.list")
    if err:
        return client.to_json(err)

    body = resp.data
    tasks = []
    for t in (getattr(body, "tasks", None) or []):
        completed_at = getattr(t, "completed_at", None) or 0
        tasks.append({
            "task_id": getattr(t, "guid", None) or "",
            "summary": getattr(t, "summary", None) or "",
            "due": getattr(t, "due", None),
            "completed": bool(completed_at),
        })

    return client.to_json({
        "tasks": tasks,
        "next_page_token": getattr(body, "next_page_token", None) or "",
        "has_more": getattr(body, "has_more", False) or False,
    })


async def _handle_update(client: FeishuClient, args: dict) -> str:
    task_id = args.get("task_id") or ""
    if not task_id:
        return client.to_json({"error": "task_id is required"})

    summary = args.get("summary")
    description = args.get("description")
    due_str = args.get("due")
    completed = args.get("completed")

    task_builder = InputTask.builder()
    update_fields = []
    if summary is not None:
        task_builder.summary(summary)
        update_fields.append("summary")
    if description is not None:
        task_builder.description(description)
        update_fields.append("description")
    if due_str is not None:
        ts = _parse_iso_to_timestamp(due_str)
        if ts is not None:
            task_builder.due(Due.builder().timestamp(ts).is_all_day(False).build())
            update_fields.append("due")
    if completed is not None:
        task_builder.completed_at(int(datetime.now().timestamp()) if completed else 0)
        update_fields.append("completed_at")

    if not update_fields:
        return client.to_json({"error": "No fields to update"})

    task_body = task_builder.build()
    patch_body = PatchTaskRequestBody.builder().task(task_body).update_fields(update_fields).build()
    request = PatchTaskRequest.builder().task_guid(task_id).request_body(patch_body).build()

    resp = await client.client.task.v2.task.apatch(request)
    client.increment_api_count()
    err = client.check_response(resp, "feishu_task.update")
    if err:
        return client.to_json(err)

    task_obj = getattr(resp.data, "task", None)
    completed_at = getattr(task_obj, "completed_at", None) or 0
    return client.to_json({
        "task_id": getattr(task_obj, "guid", None) or task_id,
        "summary": getattr(task_obj, "summary", None) or "",
        "completed": bool(completed_at),
    })


async def _handle_create_tasklist(client: FeishuClient, args: dict) -> str:
    name = args.get("name") or ""
    if not name:
        return client.to_json({"error": "name is required"})

    body = InputTasklist.builder().name(name).build()
    request = CreateTasklistRequest.builder().request_body(body).build()

    resp = await client.client.task.v2.tasklist.acreate(request)
    client.increment_api_count()
    err = client.check_response(resp, "feishu_task.create_tasklist")
    if err:
        return client.to_json(err)

    tasklist_obj = getattr(resp.data, "tasklist", None)
    tasklist_id = getattr(tasklist_obj, "guid", None) or ""
    return client.to_json({"tasklist_id": tasklist_id})


_ACTION_MAP = {
    "create": _handle_create,
    "list": _handle_list,
    "update": _handle_update,
    "create_tasklist": _handle_create_tasklist,
}


async def feishu_task_handler(client: FeishuClient, args: dict) -> str:
    action = args.get("action", "")
    handler = _ACTION_MAP.get(action)
    if handler is None:
        return json.dumps({"error": f"Unknown action: {action}"})
    return await handler(client, args)
