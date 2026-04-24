"""ReadFile 工具定义。"""

import os
from typing import Any

from core.tool.types import InternalTool, ToolParameterSchema, PermissionResult
from core.tool.tools.read_file.executor import read_file_handler, render_read_file_result


async def read_file_check_permissions(args: dict[str, Any]) -> PermissionResult:
    """ReadFile 工具的权限验证：检查路径参数并展开为绝对路径。"""
    file_path = args.get("file_path", "").strip()
    if not file_path:
        return PermissionResult.fail("file_path 不能为空")

    file_path = os.path.expanduser(file_path)
    if not os.path.isabs(file_path):
        file_path = os.path.abspath(file_path)

    if not os.path.isfile(file_path):
        return PermissionResult.fail(f"文件不存在: {file_path}")

    sanitized = dict(args)
    sanitized["file_path"] = file_path
    return PermissionResult.ok(sanitized_args=sanitized)


ReadFileTool = InternalTool(
    name="ReadFile",
    description=(
        "读取指定文件的内容。支持通过 offset 和 limit 分页读取大文件。"
        "输出带行号前缀，便于引用。"
    ),
    parameters=ToolParameterSchema(
        type="object",
        properties={
            "file_path": {
                "type": "string",
                "description": "要读取的文件的绝对路径或相对路径",
            },
            "offset": {
                "type": "number",
                "description": "从第几行开始读取（1-indexed），默认为 1",
            },
            "limit": {
                "type": "number",
                "description": "读取多少行，默认读取全部",
            },
        },
        required=["file_path"],
    ),
    handler=read_file_handler,
    check_permissions=read_file_check_permissions,
    render_result=render_read_file_result,
    category="filesystem",
    is_read_only=True,
)
