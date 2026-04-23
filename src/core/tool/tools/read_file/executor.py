"""ReadFile 工具的执行逻辑与输出格式化。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from core.tool.tools.shared.file_read_tracker import file_read_tracker
from core.tool.types import ToolResult

MAX_OUTPUT_CHARS = 100_000


@dataclass
class ReadFileData:
    content: str
    file_path: str
    total_lines: int
    lines_read: int
    offset: int


async def read_file_handler(args: dict[str, Any]) -> ToolResult:
    """读取指定文件内容，支持 offset/limit 分页。"""
    file_path: str = args.get("file_path", "")
    if not file_path:
        return ToolResult.fail("file_path is required")

    file_path = os.path.expanduser(file_path)
    if not os.path.isabs(file_path):
        file_path = os.path.abspath(file_path)

    if not os.path.isfile(file_path):
        return ToolResult.fail(f"File not found: {file_path}")

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
    except OSError as e:
        return ToolResult.fail(f"Cannot read file: {e}")

    total_lines = len(all_lines)
    offset = max(0, (args.get("offset") or 1) - 1)  # 1-indexed -> 0-indexed
    limit = args.get("limit") or total_lines

    selected = all_lines[offset: offset + limit]
    content = "".join(selected)

    if len(content) > MAX_OUTPUT_CHARS:
        half = MAX_OUTPUT_CHARS // 2
        content = content[:half] + "\n\n... [truncated] ...\n\n" + content[-half:]

    # 记录文件读取状态，供 Edit/Write 的 TOCTOU 检查使用
    is_partial = (offset > 0) or (len(selected) < total_lines)
    file_read_tracker.record_read(file_path, is_partial=is_partial)

    return ToolResult.ok(ReadFileData(
        content=content,
        file_path=file_path,
        total_lines=total_lines,
        lines_read=len(selected),
        offset=offset,
    ))


def render_read_file_result(result: ToolResult) -> str:
    """将 ReadFile 结果格式化为带行号的文本，供 LLM 阅读。"""
    if not result.success:
        return f"Error reading file: {result.error}"

    data: ReadFileData = result.data
    lines = data.content.split("\n")

    # 如果末尾是空行（来自尾部 \n），去掉以避免多余空行号
    if lines and lines[-1] == "":
        lines = lines[:-1]

    numbered = [
        f"{str(i + 1 + data.offset).rjust(6)}|{line}"
        for i, line in enumerate(lines)
    ]
    output = "\n".join(numbered)

    if data.total_lines > data.lines_read:
        output += (
            f"\n\n[Showing lines {data.offset + 1}-"
            f"{data.offset + data.lines_read} of {data.total_lines}]"
        )

    return output
