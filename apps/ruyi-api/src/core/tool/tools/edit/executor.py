"""Edit 工具执行逻辑：精确字符串替换。

增强点：
- 删除操作（new_string 为空）时自动清理残留换行符
- 引号规范化匹配（弯引号 -> 直引号）
- 写入后更新 TOCTOU 读取状态
"""

from __future__ import annotations

import os
import unicodedata
from typing import Any

from core.tool.tools.shared import write_text_atomic
from core.tool.tools.shared.file_read_tracker import file_read_tracker
from core.tool.types import ToolResult
from utils.logger import get_logger

logger = get_logger("tool.edit")

# 弯引号 -> 直引号的映射
_QUOTE_MAP = str.maketrans({
    "\u2018": "'", "\u2019": "'",   # ' '
    "\u201c": '"', "\u201d": '"',   # " "
    "\u2032": "'", "\u2033": '"',   # ′ ″
})


def _normalize_quotes(s: str) -> str:
    """将弯引号统一为直引号。"""
    return s.translate(_QUOTE_MAP)


def _normalize_path(file_path: str) -> str:
    file_path = os.path.expanduser(file_path)
    if not os.path.isabs(file_path):
        file_path = os.path.abspath(file_path)
    return file_path


def _replace_content(
    content: str,
    old_string: str,
    new_string: str,
    replace_all: bool,
) -> str | None:
    """执行替换，返回新内容。匹配失败返回 None。"""
    if old_string not in content:
        return None

    if replace_all:
        return content.replace(old_string, new_string)
    return content.replace(old_string, new_string, 1)


async def edit_file_handler(args: dict[str, Any]) -> ToolResult:
    """精确字符串替换。"""
    file_path: str = args.get("file_path", "")
    if not file_path:
        return ToolResult.fail("file_path is required")

    old_string: str = args.get("old_string", "")
    new_string: str = args.get("new_string", "")
    replace_all: bool = bool(args.get("replace_all", False))

    if old_string == new_string:
        return ToolResult.fail("old_string and new_string must be different")

    file_path = _normalize_path(file_path)
    exists = os.path.exists(file_path)

    # ── 文件不存在 + old_string 为空 = 创建新文件 ──
    if not exists:
        if old_string != "":
            return ToolResult.fail(f"File not found: {file_path}")

        try:
            write_text_atomic(file_path, new_string)
        except OSError as e:
            logger.error("Failed to create file via Edit %s: %s", file_path, e)
            return ToolResult.fail(f"写入失败: {e}")

        file_read_tracker.update_after_write(file_path)
        return ToolResult.ok({
            "type": "create",
            "file_path": file_path,
            "replace_all": replace_all,
            "matches": 0,
            "chars": len(new_string),
        })

    # ── 读取文件内容 ──
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as e:
        return ToolResult.fail(f"Cannot read file: {e}")

    # ── old_string 为空且文件非空 = 错误 ──
    if old_string == "":
        if content != "":
            return ToolResult.fail("old_string is empty but target file is not empty")
        updated = new_string
        matches = 0
    else:
        matches = content.count(old_string)

        if matches == 0:
            # 尝试引号规范化匹配
            norm_old = _normalize_quotes(old_string)
            norm_content = _normalize_quotes(content)

            if norm_old in norm_content:
                # 找到规范化后的位置，从原始内容中提取实际匹配的字符串
                idx = norm_content.index(norm_old)
                actual_old = content[idx: idx + len(old_string)]

                # 将 new_string 也做同样的引号格式适配
                actual_new = new_string
                for orig_char, norm_char in [
                    ("\u201c", '"'), ("\u201d", '"'),
                    ("\u2018", "'"), ("\u2019", "'"),
                ]:
                    if orig_char in actual_old and norm_char in new_string:
                        actual_new = actual_new.replace(norm_char, orig_char)

                matches = content.count(actual_old)
                old_string = actual_old
                new_string = actual_new
            else:
                return ToolResult.fail("String to replace not found in file")

        if matches > 1 and not replace_all:
            return ToolResult.fail(
                f"Found {matches} matches but replace_all is false; "
                "provide more context or set replace_all=true"
            )

        # ── 删除操作时的换行符特殊处理 ──
        if new_string == "":
            if not old_string.endswith("\n") and content.find(old_string + "\n") != -1:
                updated = _replace_content(content, old_string + "\n", "", replace_all)
            else:
                updated = _replace_content(content, old_string, "", replace_all)
        else:
            updated = _replace_content(content, old_string, new_string, replace_all)

        if updated is None:
            return ToolResult.fail("String to replace not found in file")

    # ── 原子写入 ──
    try:
        write_text_atomic(file_path, updated)
    except OSError as e:
        logger.error("Failed to edit file %s: %s", file_path, e)
        return ToolResult.fail(f"写入失败: {e}")

    # 更新 TOCTOU 记录
    file_read_tracker.update_after_write(file_path)

    return ToolResult.ok({
        "type": "update",
        "file_path": file_path,
        "replace_all": replace_all,
        "matches": matches,
        "chars": len(updated),
    })


def render_edit_file_result(result: ToolResult) -> str:
    """语义化返回。"""
    if not result.success:
        return f"Error: {result.error}"

    data = result.data or {}
    fp = data.get("file_path", "")

    if data.get("type") == "create":
        return f"File created successfully at: {fp}"

    if data.get("replace_all"):
        return (
            f"The file {fp} has been updated. "
            f"All occurrences were successfully replaced."
        )

    return f"The file {fp} has been updated successfully."
