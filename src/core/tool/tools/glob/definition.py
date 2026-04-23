"""Glob 工具定义与权限验证。

权限验证：
1. pattern 非空
2. 路径展开与目录存在性验证
3. ripgrep 可用性检查
"""

from __future__ import annotations

import os
import shutil
from typing import Any

from core.tool.types import InternalTool, ToolParameterSchema, PermissionResult
from core.tool.tools.glob.executor import glob_handler, render_glob_result


async def glob_check_permissions(args: dict[str, Any]) -> PermissionResult:
    """Glob 工具的权限验证。"""
    pattern = args.get("pattern", "").strip()
    if not pattern:
        return PermissionResult.fail("pattern 不能为空")

    # ripgrep 可用性
    rg_path = shutil.which("rg")
    if not rg_path:
        return PermissionResult.fail(
            "ripgrep (rg) 未安装。请先安装: https://github.com/BurntSushi/ripgrep"
        )

    # 路径展开与验证
    search_path = args.get("path", "").strip() or os.getcwd()
    search_path = os.path.expanduser(search_path)
    if not os.path.isabs(search_path):
        search_path = os.path.abspath(search_path)

    if not os.path.isdir(search_path):
        return PermissionResult.fail(f"搜索目录不存在: {search_path}")

    sanitized = dict(args)
    sanitized["path"] = search_path
    sanitized["_rg_path"] = rg_path
    return PermissionResult.ok(sanitized_args=sanitized)


GLOB_DESCRIPTION = """\
按文件名 glob 模式搜索文件。
返回匹配的文件路径列表（按修改时间排序，最近修改的在前）。
用于按文件名模式查找文件，而不是按文件内容搜索（内容搜索请使用 Grep）。
不以 **/ 开头的模式会自动添加 **/ 前缀以实现递归搜索。\
"""


GlobTool = InternalTool(
    name="Glob",
    description=GLOB_DESCRIPTION,
    parameters=ToolParameterSchema(
        type="object",
        properties={
            "pattern": {
                "type": "string",
                "description": "glob 模式，如 '*.py'、'src/**/*.ts'",
            },
            "path": {
                "type": "string",
                "description": "搜索的根目录路径，默认当前工作目录",
            },
        },
        required=["pattern"],
    ),
    handler=glob_handler,
    check_permissions=glob_check_permissions,
    render_result=render_glob_result,
    category="filesystem",
    is_read_only=True,
)
