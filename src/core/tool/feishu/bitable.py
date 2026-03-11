"""飞书多维表格工具 - 拆为 feishu_bitable（表级操作）+ feishu_bitable_record（记录操作）"""

from __future__ import annotations

import json
from typing import Any

import lark_oapi as lark
from lark_oapi.api.bitable.v1 import (
    AppTableCreateHeader,
    AppTableRecord,
    BatchCreateAppTableRecordRequestBody,
    BatchCreateAppTableRecordRequest,
    BatchDeleteAppTableRecordRequestBody,
    BatchDeleteAppTableRecordRequest,
    CreateAppRequest,
    CreateAppTableRequestBody,
    CreateAppTableRequest,
    ListAppTableFieldRequest,
    ListAppTableRecordRequest,
    ReqApp,
    ReqTable,
    UpdateAppTableRecordRequest,
)

from core.tool.feishu.client import FeishuClient
from utils import logger


# ===========================================================================
# Tool 1: feishu_bitable  (表/schema 级操作)
# ===========================================================================

feishu_bitable_def = {
    "name": "feishu_bitable",
    "description": (
        "飞书多维表格管理：创建多维表格、创建数据表、查看字段定义。"
        "action=create 需要 name；"
        "action=create_table 需要 app_token/name/fields；"
        "action=list_fields 需要 app_token/table_id。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "create_table", "list_fields"],
                "description": "操作类型",
            },
            "app_token": {"type": "string", "description": "多维表格 app_token"},
            "table_id": {"type": "string", "description": "数据表 ID"},
            "name": {"type": "string", "description": "多维表格或数据表名称"},
            "folder_token": {"type": "string", "description": "目标文件夹 token（create 可选）"},
            "fields": {
                "type": "array",
                "description": "字段定义（create_table 时必填），type: 1=文本 2=数字 3=单选 4=多选 5=日期 7=复选框",
                "items": {
                    "type": "object",
                    "properties": {
                        "field_name": {"type": "string"},
                        "type": {
                            "type": "integer",
                            "description": "1=text 2=number 3=single_select 4=multi_select 5=date 7=checkbox",
                        },
                    },
                    "required": ["field_name", "type"],
                },
            },
        },
        "required": ["action"],
    },
}


async def _bitable_create(client: FeishuClient, args: dict) -> str:
    name = args.get("name") or ""
    folder_token = args.get("folder_token")

    body_builder = ReqApp.builder().name(name)
    if folder_token is not None:
        body_builder = body_builder.folder_token(folder_token)
    request = CreateAppRequest.builder().request_body(body_builder.build()).build()

    resp = await client.client.bitable.v1.app.acreate(request)
    client.increment_api_count()

    err = client.check_response(resp, "feishu_bitable.create")
    if err:
        return client.to_json(err)

    return client.to_json({
        "app_token": resp.data.app.app_token,
        "url": getattr(resp.data.app, "url", None) or "",
    })


async def _bitable_create_table(client: FeishuClient, args: dict) -> str:
    app_token = args.get("app_token") or ""
    name = args.get("name") or ""
    fields_data = args.get("fields") or []

    req_fields = [
        AppTableCreateHeader.builder()
        .field_name(f["field_name"])
        .type(f["type"])
        .build()
        for f in fields_data
    ]
    table = ReqTable.builder().name(name).fields(req_fields).build()

    request = (
        CreateAppTableRequest.builder()
        .app_token(app_token)
        .request_body(CreateAppTableRequestBody.builder().table(table).build())
        .build()
    )

    resp = await client.client.bitable.v1.app_table.acreate(request)
    client.increment_api_count()

    err = client.check_response(resp, "feishu_bitable.create_table")
    if err:
        return client.to_json(err)

    return client.to_json({"table_id": resp.data.table_id})


async def _bitable_list_fields(client: FeishuClient, args: dict) -> str:
    app_token = args.get("app_token") or ""
    table_id = args.get("table_id") or ""

    request = (
        ListAppTableFieldRequest.builder()
        .app_token(app_token)
        .table_id(table_id)
        .build()
    )

    resp = await client.client.bitable.v1.app_table_field.alist(request)
    client.increment_api_count()

    err = client.check_response(resp, "feishu_bitable.list_fields")
    if err:
        return client.to_json(err)

    fields = [
        {"field_id": f.field_id, "field_name": f.field_name, "type": f.type}
        for f in (resp.data.items or [])
    ]
    return client.to_json({"fields": fields})


_BITABLE_ACTION_MAP = {
    "create": _bitable_create,
    "create_table": _bitable_create_table,
    "list_fields": _bitable_list_fields,
}


async def feishu_bitable_handler(client: FeishuClient, args: dict) -> str:
    action = args.get("action", "")
    handler = _BITABLE_ACTION_MAP.get(action)
    if handler is None:
        return json.dumps({"error": f"Unknown action: {action}"})
    return await handler(client, args)


# ===========================================================================
# Tool 2: feishu_bitable_record  (记录级 CRUD)
# ===========================================================================

feishu_bitable_record_def = {
    "name": "feishu_bitable_record",
    "description": (
        "飞书多维表格记录操作：查询/新增/更新/删除记录。"
        "所有操作都需要 app_token 和 table_id。"
        "action=list 可选 filter/sort/page_size/page_token；"
        "action=create 需要 records（含 fields）；"
        "action=update 需要 record_id/fields；"
        "action=delete 需要 record_ids。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "create", "update", "delete"],
                "description": "操作类型",
            },
            "app_token": {"type": "string", "description": "多维表格 app_token"},
            "table_id": {"type": "string", "description": "数据表 ID"},
            "filter": {"type": "string", "description": "筛选条件（list 可选）"},
            "sort": {"type": "string", "description": "排序条件（list 可选）"},
            "page_size": {"type": "integer", "description": "每页数量（list 可选，默认 20，最大 500）"},
            "page_token": {"type": "string", "description": "分页标记（list 可选）"},
            "records": {
                "type": "array",
                "description": "记录列表（create 时必填），每项含 fields",
                "items": {
                    "type": "object",
                    "properties": {"fields": {"type": "object"}},
                    "required": ["fields"],
                },
            },
            "record_id": {"type": "string", "description": "记录 ID（update 时必填）"},
            "fields": {"type": "object", "description": "要更新的字段名到值的映射（update 时必填）"},
            "record_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "要删除的记录 ID 列表（delete 时必填）",
            },
        },
        "required": ["action", "app_token", "table_id"],
    },
}


async def _record_list(client: FeishuClient, args: dict) -> str:
    app_token = args["app_token"]
    table_id = args["table_id"]
    page_size = args.get("page_size", 20)
    filter_str = args.get("filter")
    sort_str = args.get("sort")
    page_token = args.get("page_token")

    builder = (
        ListAppTableRecordRequest.builder()
        .app_token(app_token)
        .table_id(table_id)
        .page_size(page_size)
    )
    if filter_str is not None:
        builder = builder.filter(filter_str)
    if sort_str is not None:
        builder = builder.sort(sort_str)
    if page_token is not None:
        builder = builder.page_token(page_token)

    request = builder.build()
    resp = await client.client.bitable.v1.app_table_record.alist(request)
    client.increment_api_count()

    err = client.check_response(resp, "feishu_bitable_record.list")
    if err:
        return client.to_json(err)

    records = [
        {"record_id": r.record_id, "fields": dict(r.fields) if r.fields else {}}
        for r in (resp.data.items or [])
    ]
    return client.to_json({
        "records": records,
        "has_more": getattr(resp.data, "has_more", False),
        "page_token": getattr(resp.data, "page_token", "") or "",
    })


async def _record_create(client: FeishuClient, args: dict) -> str:
    app_token = args["app_token"]
    table_id = args["table_id"]
    records_data = args.get("records") or []

    record_list = [
        AppTableRecord.builder().fields(r["fields"]).build() for r in records_data
    ]
    request_body = BatchCreateAppTableRecordRequestBody.builder().records(record_list).build()

    request = (
        BatchCreateAppTableRecordRequest.builder()
        .app_token(app_token)
        .table_id(table_id)
        .request_body(request_body)
        .build()
    )

    resp = await client.client.bitable.v1.app_table_record.abatch_create(request)
    client.increment_api_count()

    err = client.check_response(resp, "feishu_bitable_record.create")
    if err:
        return client.to_json(err)

    record_ids = [r.record_id for r in (resp.data.records or [])]
    return client.to_json({"record_ids": record_ids})


async def _record_update(client: FeishuClient, args: dict) -> str:
    app_token = args["app_token"]
    table_id = args["table_id"]
    record_id = args.get("record_id") or ""
    fields = args.get("fields") or {}

    request = (
        UpdateAppTableRecordRequest.builder()
        .app_token(app_token)
        .table_id(table_id)
        .record_id(record_id)
        .request_body(AppTableRecord.builder().fields(fields).build())
        .build()
    )

    resp = await client.client.bitable.v1.app_table_record.aupdate(request)
    client.increment_api_count()

    err = client.check_response(resp, "feishu_bitable_record.update")
    if err:
        return client.to_json(err)

    rec = resp.data.record
    return client.to_json({
        "record_id": rec.record_id,
        "fields": dict(rec.fields) if rec.fields else {},
    })


async def _record_delete(client: FeishuClient, args: dict) -> str:
    app_token = args["app_token"]
    table_id = args["table_id"]
    record_ids = args.get("record_ids") or []

    request_body = BatchDeleteAppTableRecordRequestBody.builder().records(record_ids).build()

    request = (
        BatchDeleteAppTableRecordRequest.builder()
        .app_token(app_token)
        .table_id(table_id)
        .request_body(request_body)
        .build()
    )

    resp = await client.client.bitable.v1.app_table_record.abatch_delete(request)
    client.increment_api_count()

    err = client.check_response(resp, "feishu_bitable_record.delete")
    if err:
        return client.to_json(err)

    return client.to_json({"success": True, "deleted_count": len(record_ids)})


_RECORD_ACTION_MAP = {
    "list": _record_list,
    "create": _record_create,
    "update": _record_update,
    "delete": _record_delete,
}


async def feishu_bitable_record_handler(client: FeishuClient, args: dict) -> str:
    action = args.get("action", "")
    handler = _RECORD_ACTION_MAP.get(action)
    if handler is None:
        return json.dumps({"error": f"Unknown action: {action}"})
    return await handler(client, args)
