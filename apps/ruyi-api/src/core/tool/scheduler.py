"""工具调度器 —— 管理工具调用的完整生命周期。

完整流程:
  validating (参数解析 + check_permissions)
    -> awaiting_approval (审批模式检查)
    -> scheduled (准备执行)
    -> executing (执行 handler)
    -> render_result (格式化)
    -> OutputTruncator (裁剪/摘要)
    -> success / error / cancelled
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable, Awaitable, TYPE_CHECKING

from core.tool.types import (
    ApprovalMode,
    ConfirmDetails,
    InternalTool,
    ScheduleResult,
    ToolCallRecord,
    ToolCallStatus,
)
from core.tool.approval import ApprovalStore, ApprovalOutcome
from core.tool.output_truncator import OutputTruncator
from utils.logger import get_logger

logger = get_logger("tool.scheduler")

if TYPE_CHECKING:
    from core.output.emitter import OutputEmitter
    from core.tool.manager import ToolManager

# 摘要函数类型: (text) -> summary_text
SummarizeFn = Callable[[str], Awaitable[str]]

# 审批卡片发送回调类型: (chat_id, card_json_str) -> None
SendCardFn = Callable[[str, str], Awaitable[None]]


class ToolSchedulerConfig:
    __slots__ = ("approval_mode", "approval_timeout")

    def __init__(
        self,
        approval_mode: ApprovalMode = ApprovalMode.YOLO,
        approval_timeout: float = 120.0,
    ) -> None:
        self.approval_mode = approval_mode
        self.approval_timeout = approval_timeout


class ToolScheduler:
    """工具调度器：驱动工具调用的完整生命周期。

    Parameters
    ----------
    tool_manager:
        工具注册中心，提供工具查询和执行。
    approval_store:
        审批等待存储，桥接调度器与用户交互回调。
    truncator:
        工具输出裁剪器，控制结果写入上下文时的长度。
    summarize_fn:
        LLM 摘要函数（使用 low 模型），供 OutputTruncator 在裁剪时调用。
    config:
        调度器配置（审批模式、超时时间等）。
    send_card:
        发送审批卡片的回调函数。
    """

    def __init__(
        self,
        tool_manager: ToolManager,
        approval_store: ApprovalStore,
        truncator: OutputTruncator | None = None,
        summarize_fn: SummarizeFn | None = None,
        config: ToolSchedulerConfig | None = None,
        send_card: SendCardFn | None = None,
        emitter: OutputEmitter | None = None,
    ) -> None:
        self._tool_manager = tool_manager
        self._approval_store = approval_store
        self._truncator = truncator or OutputTruncator()
        self._summarize_fn = summarize_fn
        self._config = config or ToolSchedulerConfig()
        self._send_card = send_card
        self._emitter = emitter
        self._records: dict[str, ToolCallRecord] = {}

    @property
    def tool_manager(self) -> ToolManager:
        return self._tool_manager

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def schedule(
        self,
        call_id: str,
        tool_name: str,
        raw_args: str,
        chat_id: str = "",
        source: str = "ruyi",
        content: str = "",
    ) -> ScheduleResult:
        """单个工具调用的完整调度流程。

        Parameters
        ----------
        source:
            输出来源标识 — "ruyi" | "kairos"。
        content:
            LLM 伴随文本，仅同一批第一个工具携带。
        """

        # ── 1. validating: 参数解析 & 工具查找 ──
        record = ToolCallRecord(call_id=call_id, tool_name=tool_name)
        self._records[call_id] = record

        try:
            args = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError as e:
            return await self._set_error(record, f"参数解析失败: {e}", source)

        record.args = args

        tool = self._tool_manager.get_tool(tool_name)
        if tool is None:
            return await self._set_error(record, f"工具不存在: {tool_name}", source)

        # ── 2. validating: 调用工具的 check_permissions ──
        if tool.check_permissions is not None:
            try:
                perm_result = await tool.check_permissions(args)
            except Exception as e:
                logger.error(
                    "Tool %s check_permissions error: %s", tool_name, e, exc_info=True,
                )
                return await self._set_error(record, f"权限验证异常: {e}", source)

            if not perm_result.passed:
                return await self._set_error(
                    record, perm_result.error or "权限验证未通过", source,
                )
            if perm_result.sanitized_args is not None:
                args = perm_result.sanitized_args
                record.args = args

        # ── 3. awaiting_approval: 审批模式检查 ──
        needs_confirm = self._check_confirmation(tool)
        if needs_confirm:
            record.status = ToolCallStatus.AWAITING_APPROVAL
            record.confirm_details = needs_confirm
            logger.info(
                "Tool %s (call=%s) awaiting approval", tool_name, call_id,
            )

            if self._send_card and chat_id:
                card_json = self._build_approval_card(call_id, tool_name, args)
                try:
                    await self._send_card(chat_id, card_json)
                except Exception as e:
                    logger.error("Failed to send approval card: %s", e)

            outcome = await self._approval_store.wait_for_approval(
                call_id, timeout=self._config.approval_timeout,
            )

            if outcome != "approve":
                reason = "用户取消" if outcome == "cancel" else "审批超时"
                return await self._set_cancelled(record, reason, source)

        # ── 4. scheduled -> executing ──
        record.status = ToolCallStatus.SCHEDULED
        record.status = ToolCallStatus.EXECUTING
        logger.info("Tool executing: %s (call=%s)", tool_name, call_id)

        await self._emit_executing(record, args, source, content)

        try:
            tool_result = await self._tool_manager.execute(tool_name, args)
        except Exception as e:
            logger.error("Tool %s execution error: %s", tool_name, e, exc_info=True)
            return await self._set_error(record, str(e), source)

        if not tool_result.success:
            return await self._set_error(record, tool_result.error or "工具执行失败", source)

        # ── 5. render_result: 格式化为大模型可读的字符串 ──
        result_str = self._tool_manager.render(tool_name, tool_result)

        # ── 6. OutputTruncator: 输出裁剪 ──
        result_str = await self._truncator.truncate(result_str, self._summarize_fn)

        return await self._set_success(record, result_str, source)

    async def schedule_batch(
        self,
        tool_calls: list[dict[str, Any]],
        chat_id: str = "",
        source: str = "ruyi",
        assistant_content: str = "",
    ) -> list[ScheduleResult]:
        """批量调度 LLM 返回的 tool_calls。

        assistant_content 仅附着在第一个工具的 ToolExecutingEvent.content 上。
        只读工具并行执行，否则串行。
        """
        if self._can_parallel(tool_calls):
            tasks = [
                self.schedule(
                    call_id=tc["id"],
                    tool_name=tc["function"]["name"],
                    raw_args=tc["function"]["arguments"],
                    chat_id=chat_id,
                    source=source,
                    content=assistant_content if i == 0 else "",
                )
                for i, tc in enumerate(tool_calls)
            ]
            return list(await asyncio.gather(*tasks))

        results: list[ScheduleResult] = []
        for i, tc in enumerate(tool_calls):
            r = await self.schedule(
                call_id=tc["id"],
                tool_name=tc["function"]["name"],
                raw_args=tc["function"]["arguments"],
                chat_id=chat_id,
                source=source,
                content=assistant_content if i == 0 else "",
            )
            results.append(r)
        return results

    def get_records(self) -> list[ToolCallRecord]:
        return list(self._records.values())

    def clear_records(self) -> None:
        self._records.clear()

    # ------------------------------------------------------------------
    # 审批检查
    # ------------------------------------------------------------------

    def _check_confirmation(self, tool: InternalTool) -> ConfirmDetails | None:
        """根据 ApprovalMode 和工具属性判断是否需要确认。

        YOLO 模式：全部自动放行
        DEFAULT 模式：只读工具放行，非只读工具需要确认
        """
        if self._config.approval_mode == ApprovalMode.YOLO:
            return None

        if tool.is_read_only:
            return None

        return ConfirmDetails(
            title="工具执行确认",
            message=f"即将执行工具 {tool.name}，是否继续？",
            tool_name=tool.name,
        )

    # ------------------------------------------------------------------
    # 审批卡片构建
    # ------------------------------------------------------------------

    @staticmethod
    def _build_approval_card(
        call_id: str, tool_name: str, args: dict[str, Any],
    ) -> str:
        args_preview = json.dumps(args, ensure_ascii=False, indent=2)
        if len(args_preview) > 500:
            args_preview = args_preview[:500] + "\n..."

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "工具执行确认"},
                "template": "orange",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**工具**: `{tool_name}`\n"
                            f"**参数**:\n```json\n{args_preview}\n```"
                        ),
                    },
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "批准执行"},
                            "type": "primary",
                            "value": {"call_id": call_id, "outcome": "approve"},
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "取消"},
                            "type": "danger",
                            "value": {"call_id": call_id, "outcome": "cancel"},
                        },
                    ],
                },
            ],
        }
        return json.dumps(card, ensure_ascii=False)

    # ------------------------------------------------------------------
    # 并行判断
    # ------------------------------------------------------------------

    def _can_parallel(self, tool_calls: list[dict[str, Any]]) -> bool:
        if len(tool_calls) <= 1:
            return False
        for tc in tool_calls:
            tool = self._tool_manager.get_tool(tc["function"]["name"])
            if tool is None or not tool.is_read_only:
                return False
        return True

    # ------------------------------------------------------------------
    # 输出事件
    # ------------------------------------------------------------------

    async def _emit_executing(
        self, record: ToolCallRecord, args: dict[str, Any], source: str, content: str,
    ) -> None:
        if not self._emitter:
            return
        from core.output.types import ToolExecutingEvent

        await self._emitter.emit(ToolExecutingEvent(
            source=source,
            call_id=record.call_id,
            tool_name=record.tool_name,
            args_summary=self._summarize_args(record.tool_name, args),
            content=content,
        ))

    async def _emit_done(
        self, record: ToolCallRecord, source: str,
        success: bool, status_str: str,
        result_preview: str = "", error: str | None = None,
    ) -> None:
        if not self._emitter:
            return
        from core.output.types import ToolDoneEvent

        await self._emitter.emit(ToolDoneEvent(
            source=source,
            call_id=record.call_id,
            tool_name=record.tool_name,
            success=success,
            status=status_str,
            result_preview=result_preview,
            error=error,
            duration_ms=record.duration_ms or 0,
        ))

    @staticmethod
    def _summarize_args(tool_name: str, args: dict[str, Any]) -> str:
        """将工具参数转为简短可读的摘要字符串。"""
        if not args:
            return ""
        parts: list[str] = []
        for key, val in args.items():
            s = str(val)
            if len(s) > 60:
                s = s[:57] + "..."
            parts.append(f"{key}={s}")
        summary = ", ".join(parts)
        if len(summary) > 150:
            summary = summary[:147] + "..."
        return summary

    # ------------------------------------------------------------------
    # 状态设置
    # ------------------------------------------------------------------

    async def _set_success(
        self, record: ToolCallRecord, result_string: str, source: str = "ruyi",
    ) -> ScheduleResult:
        record.status = ToolCallStatus.SUCCESS
        record.result = result_string
        record.duration_ms = record.elapsed_ms()
        logger.info(
            "Tool %s success (call=%s, %.0fms)",
            record.tool_name, record.call_id, record.duration_ms,
        )
        preview = result_string[:500] if result_string else ""
        await self._emit_done(record, source, True, "success", result_preview=preview)
        return ScheduleResult(
            call_id=record.call_id,
            tool_name=record.tool_name,
            success=True,
            status=ToolCallStatus.SUCCESS,
            result=result_string,
            result_string=result_string,
        )

    async def _set_error(
        self, record: ToolCallRecord, error: str, source: str = "ruyi",
    ) -> ScheduleResult:
        record.status = ToolCallStatus.ERROR
        record.error = error
        record.duration_ms = record.elapsed_ms()
        logger.error(
            "Tool %s error (call=%s): %s", record.tool_name, record.call_id, error,
        )
        await self._emit_done(record, source, False, "error", error=error)
        return ScheduleResult(
            call_id=record.call_id,
            tool_name=record.tool_name,
            success=False,
            status=ToolCallStatus.ERROR,
            error=error,
        )

    async def _set_cancelled(
        self, record: ToolCallRecord, reason: str, source: str = "ruyi",
    ) -> ScheduleResult:
        record.status = ToolCallStatus.CANCELLED
        record.error = reason
        record.duration_ms = record.elapsed_ms()
        logger.warning(
            "Tool %s cancelled (call=%s): %s",
            record.tool_name, record.call_id, reason,
        )
        await self._emit_done(record, source, False, "cancelled", error=reason)
        return ScheduleResult(
            call_id=record.call_id,
            tool_name=record.tool_name,
            success=False,
            status=ToolCallStatus.CANCELLED,
            error=reason,
        )
