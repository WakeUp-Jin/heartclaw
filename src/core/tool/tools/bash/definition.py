"""Bash 工具定义。"""

from core.tool.types import InternalTool, ToolParameterSchema
from core.tool.tools.bash.executor import bash_handler, render_bash_result

BashTool = InternalTool(
    name="Bash",
    category="system",
    description=(
        "Execute a bash command or shell script. "
        "Use this to run skill scripts, system commands, or any executable. "
        "Returns stdout and stderr. "
        "For long-running commands, set a higher timeout."
    ),
    parameters=ToolParameterSchema(
        type="object",
        properties={
            "command": {
                "type": "string",
                "description": "The bash command or script path to execute",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 30)",
            },
        },
        required=["command"],
    ),
    handler=bash_handler,
    render_result=render_bash_result,
    is_read_only=False,
    should_confirm=None,
)
