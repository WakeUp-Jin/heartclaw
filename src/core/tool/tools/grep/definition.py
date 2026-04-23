"""Grep 工具定义与权限验证。

权限验证：
1. pattern 非空
2. 正则合法性检查
3. 路径展开与存在性验证
4. ripgrep 可用性检查
"""

from __future__ import annotations

import os
import re
import shutil
from typing import Any

from core.tool.types import InternalTool, ToolParameterSchema, PermissionResult
from core.tool.tools.grep.executor import grep_handler, render_grep_result


async def grep_check_permissions(args: dict[str, Any]) -> PermissionResult:
    """Grep 工具的权限验证。"""
    pattern = args.get("pattern", "").strip()
    if not pattern:
        return PermissionResult.fail("pattern 不能为空")

    # 正则合法性检查
    try:
        re.compile(pattern)
    except re.error as e:
        return PermissionResult.fail(f"无效的正则表达式: {e}")

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

    if not os.path.exists(search_path):
        return PermissionResult.fail(f"搜索路径不存在: {search_path}")

    sanitized = dict(args)
    sanitized["path"] = search_path
    sanitized["_rg_path"] = rg_path
    return PermissionResult.ok(sanitized_args=sanitized)


GREP_DESCRIPTION = """\
在文件或目录中进行正则表达式内容搜索。
支持递归搜索、文件类型过滤、上下文行显示。
使用 ripgrep(rg) 实现，速度极快。这是一个只读搜索工具。\
"""


GrepTool = InternalTool(
    name="Grep",
    description=GREP_DESCRIPTION,
    parameters=ToolParameterSchema(
        type="object",
        properties={
            "pattern": {
                "type": "string",
                "description": "正则表达式搜索模式",
            },
            "path": {
                "type": "string",
                "description": "搜索的文件或目录路径，默认当前工作目录",
            },
            "include": {
                "type": "string",
                "description": "文件 glob 过滤模式，如 '*.py'",
            },
            "context_lines": {
                "type": "integer",
                "description": "匹配行前后显示的上下文行数，默认 0",
            },
            "max_results": {
                "type": "integer",
                "description": "最大返回结果数，默认 50",
            },
        },
        required=["pattern"],
    ),
    handler=grep_handler,
    check_permissions=grep_check_permissions,
    render_result=render_grep_result,
    category="filesystem",
    is_read_only=True,
)
