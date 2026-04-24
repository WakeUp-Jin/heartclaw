"""输出后端 — 4 种内置实现。

每个后端收到 OutputEvent 后，根据事件类型自行决定是否处理、如何处理。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.output.types import (
    FinalReplyEvent,
    KairosLifecycleEvent,
    OutputEvent,
    ToolDoneEvent,
    ToolExecutingEvent,
)
from utils.logger import get_logger

if TYPE_CHECKING:
    from api.routes.ws import ConnectionManager
    from channels.feishu.channel import FeishuChannel

logger = get_logger("output.backend")


# ── FutureBackend ──────────────────────────────────────────────────


class FutureBackend:
    """将最终回复写入 Future，供 HTTP / 飞书 on_message 的 await 拿到结果。

    只响应 FinalReplyEvent 且携带 _future 的情况。
    """

    name = "future"

    async def handle(self, event: OutputEvent) -> None:
        if not isinstance(event, FinalReplyEvent):
            return
        if event._future and not event._future.done():
            event._future.set_result(event.text)


# ── LogBackend ─────────────────────────────────────────────────────


class LogBackend:
    """终端日志输出（观察 / 调试用），响应所有事件类型。"""

    name = "log"

    async def handle(self, event: OutputEvent) -> None:
        if isinstance(event, ToolExecutingEvent):
            parts = [f"[{event.source}] Tool > {event.tool_name} 开始执行"]
            if event.args_summary:
                parts.append(f"({event.args_summary})")
            if event.content:
                parts.append(f'  text="{event.content[:80]}"')
            logger.info(" ".join(parts))

        elif isinstance(event, ToolDoneEvent):
            tag = "完成" if event.success else f"失败: {event.error}"
            logger.info(
                "[%s] Tool > %s %s (%.0fms)",
                event.source, event.tool_name, tag, event.duration_ms,
            )

        elif isinstance(event, FinalReplyEvent):
            logger.info("[%s] Agent > %s", event.source, event.text[:200])

        elif isinstance(event, KairosLifecycleEvent):
            logger.info("[kairos] %s: %s", event.event, event.detail)


# ── WebSocketBackend ───────────────────────────────────────────────


class WebSocketBackend:
    """通过 WebSocket 广播事件到前端。

    不同事件类型映射为不同的 WebSocket 消息 type：
    - ToolExecutingEvent → type="tool_status" status="executing"
    - ToolDoneEvent      → type="tool_status" status="success/error/cancelled"
    - KairosLifecycleEvent → type="kairos_event"
    - FinalReplyEvent    → 不广播（HTTP 通过 Future 返回）
    """

    name = "websocket"

    def __init__(self, ws_manager: ConnectionManager) -> None:
        self._manager = ws_manager

    async def handle(self, event: OutputEvent) -> None:
        if isinstance(event, ToolExecutingEvent):
            msg = {
                "type": "tool_status",
                "data": {
                    "source": event.source,
                    "call_id": event.call_id,
                    "tool_name": event.tool_name,
                    "status": "executing",
                    "args_summary": event.args_summary,
                    "content": event.content,
                },
            }
            await self._manager.broadcast(msg)

        elif isinstance(event, ToolDoneEvent):
            data: dict = {
                "source": event.source,
                "call_id": event.call_id,
                "tool_name": event.tool_name,
                "status": event.status,
                "duration_ms": event.duration_ms,
            }
            if event.success:
                data["result_preview"] = event.result_preview[:500]
            else:
                data["error"] = event.error or ""
            msg = {"type": "tool_status", "data": data}
            await self._manager.broadcast(msg)

        elif isinstance(event, FinalReplyEvent):
            if event.source == "kairos" and event.text:
                msg = {
                    "type": "kairos_reply",
                    "data": {
                        "text": event.text,
                        "timestamp": event.timestamp,
                    },
                }
                await self._manager.broadcast(msg)

        elif isinstance(event, KairosLifecycleEvent):
            msg = {
                "type": "kairos_event",
                "data": {
                    "event": event.event,
                    "timestamp": event.timestamp,
                    "detail": event.detail,
                },
            }
            await self._manager.broadcast(msg)


# ── FeishuBackend ──────────────────────────────────────────────────


class FeishuBackend:
    """通过飞书 API 发送回复消息。

    当前只响应 FinalReplyEvent。
    发送条件与原版一致：有 chat_id、有 text、source_channel 为 feishu 或空。
    """

    name = "feishu"

    def __init__(self, channel: FeishuChannel) -> None:
        self._channel = channel

    async def handle(self, event: OutputEvent) -> None:
        if not isinstance(event, FinalReplyEvent):
            return
        if not event.chat_id or not event.text:
            return
        if event.source_channel not in ("feishu", ""):
            return
        try:
            await self._channel.send_message(event.chat_id, event.text)
        except Exception:
            logger.error(
                "FeishuBackend failed to send to chat_id=%s",
                event.chat_id,
                exc_info=True,
            )
