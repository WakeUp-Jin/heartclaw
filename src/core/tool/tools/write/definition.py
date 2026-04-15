"""Write tool definition."""

from core.tool.tools.write.executor import write_file_handler, render_write_file_result
from core.tool.types import InternalTool, ToolParameterSchema

WriteTool = InternalTool(
    name="Write",
    category="filesystem",
    description=(
        "整文件写入：文件不存在则创建，存在则覆盖。"
        "用于新建文件或完整重写；局部修改优先使用 Edit。"
    ),
    parameters=ToolParameterSchema(
        type="object",
        properties={
            "file_path": {
                "type": "string",
                "description": "要写入的文件路径（绝对路径或相对路径）",
            },
            "content": {
                "type": "string",
                "description": "要写入的完整文件内容",
            },
        },
        required=["file_path", "content"],
    ),
    handler=write_file_handler,
    render_result=render_write_file_result,
    is_read_only=False,
    should_confirm=None,
)
