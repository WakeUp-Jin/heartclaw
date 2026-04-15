"""CronDelete 工具定义。"""

from core.tool.types import InternalTool, ToolParameterSchema
from core.tool.tools.cron_delete.executor import cron_delete_handler, render_cron_delete_result

CronDeleteTool = InternalTool(
    name="CronDelete",
    category="scheduler",
    description="删除一个已创建的定时任务。需要提供 CronCreate 返回的任务 ID。",
    parameters=ToolParameterSchema(
        type="object",
        properties={
            "id": {
                "type": "string",
                "description": "要删除的定时任务 ID（CronCreate 返回的 8 位 hex ID）",
            },
        },
        required=["id"],
    ),
    handler=cron_delete_handler,
    render_result=render_cron_delete_result,
    is_read_only=False,
    should_confirm=None,
)
