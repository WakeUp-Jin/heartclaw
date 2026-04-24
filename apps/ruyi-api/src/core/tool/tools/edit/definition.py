"""Edit 工具定义与权限验证。

权限验证：
1. 路径参数检查与展开
2. 文件存在性检查
3. TOCTOU 防护（检查文件是否在读取后被修改）
"""

from __future__ import annotations

import os
from typing import Any

from core.tool.types import InternalTool, ToolParameterSchema, PermissionResult
from core.tool.tools.edit.executor import edit_file_handler, render_edit_file_result
from core.tool.tools.shared.file_read_tracker import file_read_tracker


async def edit_check_permissions(args: dict[str, Any]) -> PermissionResult:
    """Edit 工具的权限验证：路径检查 + TOCTOU 防护。"""
    file_path = args.get("file_path", "").strip()
    if not file_path:
        return PermissionResult.fail("file_path 不能为空")

    file_path = os.path.expanduser(file_path)
    if not os.path.isabs(file_path):
        file_path = os.path.abspath(file_path)

    old_string = args.get("old_string", "")

    # 文件不存在且 old_string 非空 -> 拒绝
    if not os.path.exists(file_path) and old_string != "":
        return PermissionResult.fail(f"文件不存在: {file_path}")

    # TOCTOU 防护：文件存在时检查是否被读取过、是否被修改过
    if os.path.exists(file_path):
        passed, message = file_read_tracker.check_freshness(file_path)
        if not passed:
            return PermissionResult.fail(message)

    sanitized = dict(args)
    sanitized["file_path"] = file_path
    return PermissionResult.ok(sanitized_args=sanitized)


EDIT_DESCRIPTION = """\
在文件中执行精确的字符串替换。

用法：
- 编辑之前，必须在本轮对话中至少使用一次 ReadFile 工具读取文件。\
如果未读取文件就尝试编辑，此工具会报错。
- 编辑来自 ReadFile 工具输出的文本时，确保保留行号前缀之后的精确缩进（制表符/空格）。\
行号前缀格式为：行号 + 制表符。其后的所有内容才是需要匹配的实际文件内容。\
切勿将行号前缀的任何部分包含在 old_string 或 new_string 中。
- 始终优先编辑代码库中的现有文件。除非明确要求，否则不要编写新文件。
- 仅在用户明确要求时才使用表情符号。除非被要求，否则避免在文件中添加表情符号。
- 使用最小的、明显唯一的 old_string —— 通常 2-4 行相邻代码就足够了。\
当少量上下文已能唯一标识目标时，避免包含 10 行以上的上下文。
- 如果 old_string 在文件中不唯一，编辑将失败。\
提供更长的字符串并附带更多上下文以使其唯一，或者使用 replace_all 更改每一处实例。
- 使用 replace_all 在整个文件中替换和重命名字符串。例如重命名某个变量。\
"""


EditTool = InternalTool(
    name="Edit",
    description=EDIT_DESCRIPTION,
    parameters=ToolParameterSchema(
        type="object",
        properties={
            "file_path": {
                "type": "string",
                "description": "文件的绝对路径（必须为绝对路径）",
            },
            "old_string": {
                "type": "string",
                "description": "文件中要被替换的原始文本",
            },
            "new_string": {
                "type": "string",
                "description": "用于替换的新文本",
            },
            "replace_all": {
                "type": "boolean",
                "description": "是否替换所有匹配项（默认 false）",
            },
        },
        required=["file_path", "old_string", "new_string"],
    ),
    handler=edit_file_handler,
    check_permissions=edit_check_permissions,
    render_result=render_edit_file_result,
    category="filesystem",
    is_read_only=False,
)
