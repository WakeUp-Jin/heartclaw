"""Write 工具定义与权限验证。

权限验证：
1. 路径参数检查与展开
2. 父目录检查（不存在则自动创建）
3. TOCTOU 防护（覆盖已有文件时检查是否在读取后被修改）
"""

from __future__ import annotations

import os
from typing import Any

from core.tool.types import InternalTool, ToolParameterSchema, PermissionResult
from core.tool.tools.write.executor import write_file_handler, render_write_file_result
from core.tool.tools.shared.file_read_tracker import file_read_tracker


async def write_check_permissions(args: dict[str, Any]) -> PermissionResult:
    """Write 工具的权限验证：路径检查 + 目录创建 + TOCTOU 防护。"""
    file_path = args.get("file_path", "").strip()
    if not file_path:
        return PermissionResult.fail("file_path 不能为空")

    file_path = os.path.expanduser(file_path)
    if not os.path.isabs(file_path):
        file_path = os.path.abspath(file_path)

    # 父目录检查：不存在则自动创建
    parent_dir = os.path.dirname(file_path)
    if parent_dir and not os.path.isdir(parent_dir):
        try:
            os.makedirs(parent_dir, exist_ok=True)
        except OSError as e:
            return PermissionResult.fail(f"无法创建父目录 {parent_dir}: {e}")

    # TOCTOU 防护：文件已存在时（覆盖操作）检查读取状态
    if os.path.exists(file_path):
        passed, message = file_read_tracker.check_freshness(file_path)
        if not passed:
            return PermissionResult.fail(message)

    sanitized = dict(args)
    sanitized["file_path"] = file_path
    return PermissionResult.ok(sanitized_args=sanitized)


WRITE_DESCRIPTION = """\
将文件写入本地文件系统。
修改现有文件时请优先使用编辑工具 —— 仅当创建新文件或完全重写文件时才使用此工具。
在覆盖文件之前，必须先读取文件的内容。\
"""


WriteTool = InternalTool(
    name="Write",
    description=WRITE_DESCRIPTION,
    parameters=ToolParameterSchema(
        type="object",
        properties={
            "file_path": {
                "type": "string",
                "description": "文件的绝对路径（必须为绝对路径，不能为相对路径）",
            },
            "content": {
                "type": "string",
                "description": "要写入文件的内容",
            },
        },
        required=["file_path", "content"],
    ),
    handler=write_file_handler,
    check_permissions=write_check_permissions,
    render_result=render_write_file_result,
    category="filesystem",
    is_read_only=False,
)
