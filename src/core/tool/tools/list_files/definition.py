"""ListFiles 工具定义。"""

import os
from typing import Any

from core.tool.types import InternalTool, ToolParameterSchema, PermissionResult
from core.tool.tools.list_files.executor import list_files_handler, render_list_files_result


async def list_files_check_permissions(args: dict[str, Any]) -> PermissionResult:
    """ListFiles 工具的权限验证：检查路径参数并展开为绝对路径。"""
    folder_path = args.get("folder_path", "").strip()
    if not folder_path:
        return PermissionResult.fail("folder_path 不能为空")

    folder_path = os.path.expanduser(folder_path)
    if not os.path.isabs(folder_path):
        folder_path = os.path.abspath(folder_path)

    if not os.path.isdir(folder_path):
        return PermissionResult.fail(f"目录不存在: {folder_path}")

    sanitized = dict(args)
    sanitized["folder_path"] = folder_path
    return PermissionResult.ok(sanitized_args=sanitized)


ListFilesTool = InternalTool(
    name="ListFiles",
    description="列出指定文件夹下的所有文件和子文件夹",
    parameters=ToolParameterSchema(
        type="object",
        properties={
            "folder_path": {
                "type": "string",
                "description": "文件夹路径",
            },
        },
        required=["folder_path"],
    ),
    handler=list_files_handler,
    check_permissions=list_files_check_permissions,
    render_result=render_list_files_result,
    category="filesystem",
    is_read_only=True,
)
