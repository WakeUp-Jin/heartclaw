"""WriteFile 工具的执行逻辑。

文件不存在则创建（含父目录），文件存在则覆盖写入。
"""

from __future__ import annotations

import os
from typing import Any

from core.tool.types import ToolResult
from utils.logger import get_logger

logger = get_logger("tool.write_file")


async def write_file_handler(args: dict[str, Any]) -> ToolResult:
    """写入文件：不存在则创建，存在则覆盖。"""
    file_path: str = args.get("file_path", "")
    if not file_path:
        return ToolResult.fail("file_path is required")

    content: str = args.get("content", "")

    file_path = os.path.expanduser(file_path)
    if not os.path.isabs(file_path):
        file_path = os.path.abspath(file_path)

    created = not os.path.exists(file_path)

    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        logger.error("Failed to write file %s: %s", file_path, e)
        return ToolResult.fail(f"写入失败: {e}")

    action = "创建" if created else "覆盖写入"
    logger.info("WriteFile %s: %s (%d chars)", action, file_path, len(content))
    return ToolResult.ok(f"文件已{action}: {file_path} ({len(content)} 字符)")


def render_write_file_result(result: ToolResult) -> str:
    if not result.success:
        return f"Error: {result.error}"
    return str(result.data)
