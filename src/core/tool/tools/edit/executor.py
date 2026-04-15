"""Edit tool executor: exact in-file string replacement."""

from __future__ import annotations

import os
from typing import Any

from core.tool.tools.shared import write_text_atomic
from core.tool.types import ToolResult
from utils.logger import get_logger

logger = get_logger("tool.edit")


def _normalize_path(file_path: str) -> str:
    file_path = os.path.expanduser(file_path)
    if not os.path.isabs(file_path):
        file_path = os.path.abspath(file_path)
    return file_path


async def edit_file_handler(args: dict[str, Any]) -> ToolResult:
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

    if not exists:
        if old_string != "":
            return ToolResult.fail(f"File not found: {file_path}")

        try:
            write_text_atomic(file_path, new_string)
        except OSError as e:
            logger.error("Failed to create file via Edit %s: %s", file_path, e)
            return ToolResult.fail(f"写入失败: {e}")

        return ToolResult.ok(
            {
                "type": "create",
                "file_path": file_path,
                "replace_all": replace_all,
                "matches": 0,
                "chars": len(new_string),
            }
        )

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as e:
        return ToolResult.fail(f"Cannot read file: {e}")

    if old_string == "":
        if content != "":
            return ToolResult.fail("old_string is empty but target file is not empty")

        updated = new_string
        matches = 0
    else:
        matches = content.count(old_string)
        if matches == 0:
            return ToolResult.fail("String to replace not found in file")
        if matches > 1 and not replace_all:
            return ToolResult.fail(
                f"Found {matches} matches but replace_all is false; provide more context or set replace_all=true"
            )
        updated = (
            content.replace(old_string, new_string)
            if replace_all
            else content.replace(old_string, new_string, 1)
        )

    try:
        write_text_atomic(file_path, updated)
    except OSError as e:
        logger.error("Failed to edit file %s: %s", file_path, e)
        return ToolResult.fail(f"写入失败: {e}")

    return ToolResult.ok(
        {
            "type": "update",
            "file_path": file_path,
            "replace_all": replace_all,
            "matches": matches,
            "chars": len(updated),
        }
    )


def render_edit_file_result(result: ToolResult) -> str:
    if not result.success:
        return f"Error: {result.error}"

    data = result.data or {}
    action = "创建" if data.get("type") == "create" else "更新"
    return (
        f"文件已{action}: {data.get('file_path')} "
        f"(replace_all={data.get('replace_all')}, matches={data.get('matches')}, chars={data.get('chars')})"
    )
