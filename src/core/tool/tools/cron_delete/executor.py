"""CronDelete 工具的执行逻辑。"""

from __future__ import annotations

from typing import Any

from core.tool.types import ToolResult
from scheduler.cron_tasks import read_cron_tasks, remove_cron_tasks


async def cron_delete_handler(args: dict[str, Any]) -> ToolResult:
    task_id: str = args.get("id", "").strip()
    if not task_id:
        return ToolResult.fail("id 不能为空")

    tasks = read_cron_tasks()
    if not any(t.id == task_id for t in tasks):
        return ToolResult.fail(f"任务 {task_id} 不存在")

    removed = remove_cron_tasks([task_id])
    if removed == 0:
        return ToolResult.fail(f"删除任务 {task_id} 失败")

    return ToolResult.ok({"id": task_id})


def render_cron_delete_result(result: ToolResult) -> str:
    if not result.success:
        return f"删除失败: {result.error}"
    return f"已删除定时任务 {result.data['id']}。"
