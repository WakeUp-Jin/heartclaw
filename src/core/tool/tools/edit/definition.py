"""Edit tool definition."""

from core.tool.tools.edit.executor import edit_file_handler, render_edit_file_result
from core.tool.types import InternalTool, ToolParameterSchema

EditTool = InternalTool(
    name="Edit",
    category="filesystem",
    description=(
        "在文件中执行精确字符串替换。优先用于修改已有文件；"
        "可通过 replace_all 控制是否替换全部匹配项。"
    ),
    parameters=ToolParameterSchema(
        type="object",
        properties={
            "file_path": {
                "type": "string",
                "description": "要编辑的文件路径（绝对路径或相对路径）",
            },
            "old_string": {
                "type": "string",
                "description": "待替换的原始字符串",
            },
            "new_string": {
                "type": "string",
                "description": "替换后的字符串",
            },
            "replace_all": {
                "type": "boolean",
                "description": "是否替换所有匹配项，默认 false",
            },
        },
        required=["file_path", "old_string", "new_string"],
    ),
    handler=edit_file_handler,
    render_result=render_edit_file_result,
    is_read_only=False,
    should_confirm=None,
)
