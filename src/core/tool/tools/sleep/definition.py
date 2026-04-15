"""SleepTool 定义 — KAIROS 自治模式专属工具。"""

from core.tool.types import InternalTool, ToolParameterSchema
from core.tool.tools.sleep.executor import sleep_handler, render_sleep_result

SleepTool = InternalTool(
    name="Sleep",
    category="kairos",
    description=(
        "控制下次醒来的等待时长。仅在 KAIROS 自治模式下可用。\n"
        "\n"
        "当你收到 <tick> 消息后判断当前没有需要处理的工作时，必须调用此工具。\n"
        "每次醒来都会消耗一次 API 调用费用，请合理选择休息时长：\n"
        "  - 正在持续工作，等待外部结果 → 30~60 秒\n"
        "  - 暂时无事可做 → 120~300 秒\n"
        "  - 深夜或长时间无任务 → 300~600 秒\n"
        "\n"
        "不要在有事可做时调用此工具，直接继续工作即可。"
    ),
    parameters=ToolParameterSchema(
        type="object",
        properties={
            "seconds": {
                "type": "integer",
                "description": "休息秒数，必须为正整数",
            },
        },
        required=["seconds"],
    ),
    handler=sleep_handler,
    render_result=render_sleep_result,
    is_read_only=True,
    should_confirm=None,
)
