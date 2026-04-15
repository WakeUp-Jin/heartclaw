"""CronCreate 工具定义。"""

from core.tool.types import InternalTool, ToolParameterSchema
from core.tool.tools.cron_create.executor import cron_create_handler, render_cron_create_result

CronCreateTool = InternalTool(
    name="CronCreate",
    category="scheduler",
    description=(
        "创建一个定时任务。到指定时间后，系统会自动将 prompt 作为用户输入交给 Agent 执行。\n"
        "\n"
        "时间格式为标准 5 字段 cron 表达式（本地时间）: 分 时 日 月 星期\n"
        "示例:\n"
        "  - */5 * * * *     每5分钟\n"
        "  - 0 9 * * *       每天9:00\n"
        "  - 0 9 * * 1-5     工作日9:00\n"
        "  - 30 14 11 4 *    4月11日14:30（一次性）\n"
        "\n"
        "重要: 当用户的需求是模糊的时间（如「每天早上9点」），请避开 :00 和 :30 这类整点，"
        "选一个偏移的分钟数（如 57 8 代替 0 9），以分散系统负载。\n"
        "\n"
        "recurring=true 表示循环任务（默认），recurring=false 表示一次性任务。"
        "一次性任务请将 cron 的日/月字段固定到具体日期。"
    ),
    parameters=ToolParameterSchema(
        type="object",
        properties={
            "cron": {
                "type": "string",
                "description": "标准 5 字段 cron 表达式（本地时间）: 分 时 日 月 星期",
            },
            "prompt": {
                "type": "string",
                "description": "到期时要执行的 prompt 内容",
            },
            "recurring": {
                "type": "boolean",
                "description": "true=循环任务（默认），false=一次性任务（触发后自动删除）",
            },
        },
        required=["cron", "prompt"],
    ),
    handler=cron_create_handler,
    render_result=render_cron_create_result,
    is_read_only=False,
    should_confirm=None,
)
