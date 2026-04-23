"""Write 工具执行逻辑：创建或覆盖完整文件内容。

增强点：
- 写入后更新 TOCTOU 读取状态
"""

from __future__ import annotations

import os
from typing import Any

from core.tool.tools.shared import write_text_atomic
from core.tool.tools.shared.file_read_tracker import file_read_tracker
from core.tool.types import ToolResult
from utils.logger import get_logger

logger = get_logger("tool.write")


def _normalize_path(file_path: str) -> str:
    file_path = os.path.expanduser(file_path)
    if not os.path.isabs(file_path):
        file_path = os.path.abspath(file_path)
    return file_path


async def write_file_handler(args: dict[str, Any]) -> ToolResult:
    """创建或覆盖文件。"""
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

    # 更新 TOCTOU 记录
    file_read_tracker.update_after_write(file_path)

    action = "create" if created else "update"
    logger.info("Write %s: %s (%d chars)", action, file_path, len(content))
    return ToolResult.ok({
        "type": action,
        "file_path": file_path,
        "chars": len(content),
    })


def render_write_file_result(result: ToolResult) -> str:
    """语义化返回。"""
    if not result.success:
        return f"Error: {result.error}"

    data = result.data or {}
    fp = data.get("file_path", "")

    if data.get("type") == "create":
        return f"File created successfully at: {fp}"

    return f"The file {fp} has been updated successfully."
