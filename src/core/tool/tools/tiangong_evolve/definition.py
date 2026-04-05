"""天工锻造令工具定义。"""

from core.tool.types import InternalTool, ToolParameterSchema
from core.tool.tools.tiangong_evolve.executor import (
    tiangong_evolve_handler,
    render_evolve_result,
)

TianGongEvolveTool = InternalTool(
    name="TianGongEvolve",
    category="tiangong",
    description=(
        "向天工下达锻造令，请求锻造新的 CLI 工具。"
        "天工会在下次巡查时开始锻造（默认每 15 分钟巡查一次）。"
        "锻造完成后，新工具将出现在 TianGongToolList Skill 中，"
        "届时可通过 Bash 工具直接调用。"
        "仅在用户明确需要如意具备新的持久能力时使用。"
    ),
    parameters=ToolParameterSchema(
        type="object",
        properties={
            "task": {
                "type": "string",
                "description": (
                    "需要锻造的工具的详细描述，包括功能目标、"
                    "期望的命令行用法、输入输出格式、外部依赖等"
                ),
            },
            "tool_name": {
                "type": "string",
                "description": (
                    "工具名称（英文、短横线分隔，如 weather-tool）。"
                    "不传则自动从 task 推导"
                ),
            },
            "target_os": {
                "type": "string",
                "description": (
                    "可选：目标运行系统（如 linux / macos / windows）。"
                    "不传则默认使用如意当前运行系统"
                ),
            },
            "target_arch": {
                "type": "string",
                "description": (
                    "可选：目标运行架构（如 x86_64 / aarch64）。"
                    "不传则默认使用如意当前运行架构"
                ),
            },
            "target_env_note": {
                "type": "string",
                "description": (
                    "可选：目标环境补充说明（例如"
                    "“最终运行在用户本机 macOS M 系列”）"
                ),
            },
        },
        required=["task"],
    ),
    handler=tiangong_evolve_handler,
    render_result=render_evolve_result,
    is_read_only=False,
    should_confirm=True,
)
