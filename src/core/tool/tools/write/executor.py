"""Write tool executor: create or overwrite full file content."""

from __future__ import annotations

import os
from typing import Any

from core.tool.tools.shared import write_text_atomic
from core.tool.types import ToolResult
from utils.logger import get_logger

logger = get_logger("tool.write")


def _normalize_path(file_path: str) -> str:
    file_path = os.path.expanduser(file_path)
    if not os.path.isabs(file_path):
        file_path = os.path.abspath(file_path)
    return file_path


async def write_file_handler(args: dict[str, Any]) -> ToolResult:
    file_path: str = args.get("file_path", "")
    if not file_path:
        return ToolResult.fail("file_path is required")

    content: str = args.get("content", "")
    file_path = _normalize_path(file_path)
    created = not os.path.exists(file_path)

    try:
        write_text_atomic(file_path, content)
    except OSError as e:
        logger.error("Failed to write file %s: %s", file_path, e)
        return ToolResult.fail(f"写入失败: {e}")

    action = "create" if created else "update"
    logger.info("Write %s: %s (%d chars)", action, file_path, len(content))
    return ToolResult.ok(
        {
            "type": action,
            "file_path": file_path,
            "chars": len(content),
        }
    )


def render_write_file_result(result: ToolResult) -> str:
    if not result.success:
        return f"Error: {result.error}"

    data = result.data or {}
    action = "创建" if data.get("type") == "create" else "覆盖更新"
    return f"文件已{action}: {data.get('file_path')} ({data.get('chars')} 字符)"
