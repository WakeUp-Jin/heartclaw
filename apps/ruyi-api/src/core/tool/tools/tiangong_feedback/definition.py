"""天工反馈重锻工具定义。"""

from core.tool.types import InternalTool, ToolParameterSchema
from core.tool.tools.tiangong_feedback.executor import (
    tiangong_feedback_handler,
    render_feedback_result,
)

TianGongFeedbackTool = InternalTool(
    name="TianGongFeedback",
    description=(
        "向天工反馈锻造工具的运行错误，请求重新锻造修复。"
        "天工会在下次巡查时基于之前的锻造记录和 Agent 会话上下文进行修复。"
        "仅在已锻造的工具运行出错、需要天工修复时使用。\n\n"
        "使用前请先读取 .heartclaw/tiangong/forge-logs/{tool_name}.md "
        "获取该工具的源码路径、锻造令路径、Agent 会话记录路径等信息。\n\n"
        "你需要自己编写完整的反馈重锻令 Markdown 内容传入 content 参数。"
        "重锻令必须以 `# 反馈重锻令：{tool_name}` 作为标题，"
        "并在元信息中包含 `- 锻造类型：重锻（error_feedback）`。"
        "内容应包含：错误信息、锻造记录中的相关文件路径、"
        "Agent 会话记录路径（如有）、重锻流程说明。"
    ),
    parameters=ToolParameterSchema(
        type="object",
        properties={
            "tool_name": {
                "type": "string",
                "description": (
                    "报错的工具名称（与锻造时一致，"
                    "如 weather-tool）"
                ),
            },
            "content": {
                "type": "string",
                "description": (
                    "反馈重锻令的完整 Markdown 内容。"
                    "标题必须是 `# 反馈重锻令：{tool_name}`"
                ),
            },
        },
        required=["tool_name", "content"],
    ),
    handler=tiangong_feedback_handler,
    render_result=render_feedback_result,
    category="tiangong",
    is_read_only=False,
)
