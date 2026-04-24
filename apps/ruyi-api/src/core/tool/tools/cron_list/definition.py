"""CronList 工具定义。"""

from core.tool.types import InternalTool, ToolParameterSchema
from core.tool.tools.cron_list.executor import cron_list_handler, render_cron_list_result

CronListTool = InternalTool(
    name="CronList",
    description="列出所有已创建的定时任务，包括任务 ID、cron 时间、类型和 prompt 内容。",
    parameters=ToolParameterSchema(
        type="object",
        properties={},
        required=[],
    ),
    handler=cron_list_handler,
    render_result=render_cron_list_result,
    category="scheduler",
    is_read_only=True,
)
