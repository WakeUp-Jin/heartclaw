"""天工锻造令工具定义。"""

from core.tool.types import InternalTool, ToolParameterSchema
from core.tool.tools.tiangong_evolve.executor import (
    tiangong_evolve_handler,
    render_evolve_result,
)

TianGongEvolveTool = InternalTool(
    name="TianGongEvolve",
    description=(
        "向天工下达锻造令，请求锻造新的 CLI 工具。"
        "天工会在下次巡查时开始锻造（默认每 15 分钟巡查一次）。"
        "锻造完成后，新工具将出现在 TianGongToolList Skill 中，"
        "届时可通过 Bash 工具直接调用。"
        "仅在用户明确需要如意具备新的持久能力时使用。\n\n"
        "你需要自己编写完整的锻造令 Markdown 内容传入 content 参数。"
        "锻造令必须以 `# 锻造令：{tool_name}` 作为标题，"
        "并在元信息中包含 `- 锻造类型：首次`。"
        "内容应包含：需求描述、运行环境信息、构建提示等。"
        "请优先考虑使用 Rust 实现，因为天工运行环境以 Rust 工具链为主。"
    ),
    parameters=ToolParameterSchema(
        type="object",
        properties={
            "tool_name": {
                "type": "string",
                "description": (
                    "工具名称（英文、短横线分隔，如 weather-tool）"
                ),
            },
            "content": {
                "type": "string",
                "description": (
                    "锻造令的完整 Markdown 内容。"
                    "标题必须是 `# 锻造令：{tool_name}`"
                ),
            },
        },
        required=["tool_name", "content"],
    ),
    handler=tiangong_evolve_handler,
    render_result=render_evolve_result,
    category="tiangong",
    is_read_only=False,
)
