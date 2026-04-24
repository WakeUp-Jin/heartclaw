"""CronCreate 工具的执行逻辑。"""

from __future__ import annotations

from typing import Any

from core.agent.context_vars import current_chat_id
from core.tool.types import ToolResult
from scheduler.cron_parser import cron_to_human, has_future_match, is_valid_cron
from scheduler.cron_tasks import add_cron_task


async def cron_create_handler(args: dict[str, Any]) -> ToolResult:
    cron: str = args.get("cron", "").strip()
    prompt: str = args.get("prompt", "").strip()
    recurring: bool = args.get("recurring", True)

    if not cron:
        return ToolResult.fail("cron 表达式不能为空")
    if not prompt:
        return ToolResult.fail("prompt 不能为空")

    if not is_valid_cron(cron):
        return ToolResult.fail(
            f"无效的 cron 表达式: '{cron}'。"
            "需要标准 5 字段格式: 分 时 日 月 星期"
        )

    if not has_future_match(cron):
        return ToolResult.fail(
            f"cron 表达式 '{cron}' 在未来一年内没有匹配的时间点"
        )

    chat_id = current_chat_id.get()

    try:
        task_id = add_cron_task(cron, prompt, chat_id, recurring)
    except ValueError as e:
        return ToolResult.fail(str(e))

    human = cron_to_human(cron)
    return ToolResult.ok({
        "id": task_id,
        "humanSchedule": human,
        "recurring": recurring,
    })


def render_cron_create_result(result: ToolResult) -> str:
    if not result.success:
        return f"创建失败: {result.error}"

    data = result.data
    task_id = data["id"]
    human = data["humanSchedule"]
    recurring = data["recurring"]

    if recurring:
        return (
            f"已创建循环定时任务 {task_id} ({human})。"
            f"使用 CronDelete 工具可取消此任务。"
        )
    return (
        f"已创建一次性定时任务 {task_id} ({human})。"
        f"触发后将自动删除。"
    )
