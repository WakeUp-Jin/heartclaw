"""飞书卡片回传交互回调路由。

当用户点击审批卡片上的按钮后，飞书开放平台会向此端点发送 HTTP POST 回调。
回调中包含 action.value 字段，携带 call_id 和 outcome，用于唤醒
ToolScheduler 中等待审批的 asyncio.Future。

TODO: 接入飞书开放平台
  1. 在飞书开发者后台 -> 应用功能 -> 机器人 中配置「消息卡片请求网址」
     指向本服务的 /api/card_callback 端点
  2. 实现请求签名验证（Verification Token 或 Encrypt Key）
  3. 如需更新卡片内容（标记已审批），需在响应体中返回卡片更新 JSON

参考文档: https://open.feishu.cn/document/feishu-cards/card-callback-communication
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from utils.logger import logger

router = APIRouter()

_approval_store: Any = None


def set_approval_store(store: Any) -> None:
    global _approval_store
    _approval_store = store


@router.post("/api/card_callback")
async def card_callback(request: Request):
    """接收飞书卡片回传交互回调。

    飞书回调 body 结构 (新版):
    {
        "operator": {"open_id": "ou_xxx", ...},
        "action": {
            "value": {"call_id": "xxx", "outcome": "approve" | "cancel"},
            "tag": "button"
        },
        "token": "xxx",
        ...
    }

    需在 3 秒内响应。
    """
    body = await request.json()

    # TODO: 验证请求签名 (Verification Token)

    action = body.get("action", {})
    value = action.get("value", {})
    call_id = value.get("call_id")
    outcome = value.get("outcome", "cancel")

    if not call_id:
        logger.warning("card_callback: missing call_id in action.value")
        return {"toast": {"type": "warning", "content": "无效的回调请求"}}

    operator = body.get("operator", {})
    open_id = operator.get("open_id", "unknown")
    logger.info(
        "Card callback: call_id=%s, outcome=%s, operator=%s",
        call_id, outcome, open_id,
    )

    if _approval_store is None:
        logger.error("card_callback: approval_store not initialized")
        return {"toast": {"type": "error", "content": "服务未就绪"}}

    resolved = _approval_store.resolve_approval(call_id, outcome)

    if resolved:
        toast_content = "已批准执行" if outcome == "approve" else "已取消"
    else:
        toast_content = "该请求已过期或已处理"

    return {"toast": {"type": "info", "content": toast_content}}
