"""WriteFile 工具定义。"""

from core.tool.types import InternalTool, ToolParameterSchema
from core.tool.tools.write_file.executor import (
    write_file_handler,
    render_write_file_result,
)

WriteFileTool = InternalTool(
    name="WriteFile",
    category="filesystem",
    description=(
        "写入文件内容。文件不存在则自动创建（含父目录），文件存在则覆盖写入。"
    ),
    parameters=ToolParameterSchema(
        type="object",
        properties={
            "file_path": {
                "type": "string",
                "description": "要写入的文件的绝对路径或相对路径",
            },
            "content": {
                "type": "string",
                "description": "要写入的文件内容",
            },
        },
        required=["file_path", "content"],
    ),
    handler=write_file_handler,
    render_result=render_write_file_result,
    is_read_only=False,
    should_confirm=None,
)
