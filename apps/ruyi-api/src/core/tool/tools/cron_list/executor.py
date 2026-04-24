"""CronList 工具的执行逻辑。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core.tool.types import ToolResult
from scheduler.cron_parser import cron_to_human
from scheduler.cron_tasks import read_cron_tasks


async def cron_list_handler(args: dict[str, Any]) -> ToolResult:
    tasks = read_cron_tasks()
    if not tasks:
        return ToolResult.ok("暂无定时任务。")

    lines: list[str] = []
    for t in tasks:
        human = cron_to_human(t.cron)
        kind = "循环" if t.recurring else "一次性"
        created = datetime.fromtimestamp(t.created_at).strftime("%m-%d %H:%M")
        lines.append(f"{t.id} — {human} ({kind}, 创建于 {created}): {t.prompt}")

    return ToolResult.ok("\n".join(lines))


def render_cron_list_result(result: ToolResult) -> str:
    if not result.success:
        return f"查询失败: {result.error}"
    return result.data
