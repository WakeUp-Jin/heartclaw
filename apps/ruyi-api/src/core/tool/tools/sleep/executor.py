"""SleepTool 执行逻辑。

仅记录 LLM 请求的 sleep 秒数并返回确认。
实际的等待由 QueueProcessor 在 tick 结束后的尾部调度中执行。
"""

from __future__ import annotations

from typing import Any

from core.tool.types import ToolResult


async def sleep_handler(args: dict[str, Any]) -> ToolResult:
    seconds = args.get("seconds", 300)
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        return ToolResult.fail("seconds 必须为正数")
    return ToolResult.ok({"seconds": int(seconds)})


def render_sleep_result(result: ToolResult) -> str:
    if not result.success:
        return f"Sleep 失败: {result.error}"
    return f"已休息 {result.data['seconds']} 秒"
