"""Glob 工具的执行逻辑 —— 使用 ripgrep --files --glob 实现。"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any

from core.tool.types import ToolResult
from utils.logger import get_logger

logger = get_logger("tool.glob")

MAX_FILES = 1000
DEFAULT_TIMEOUT_SEC = 30


@dataclass
class GlobResultData:
    """Glob 工具执行结果的结构化数据。"""
    files: list[dict[str, Any]] = field(default_factory=list)
    total_count: int = 0
    pattern: str = ""
    search_path: str = ""


async def glob_handler(args: dict[str, Any]) -> ToolResult:
    """使用 ripgrep --files --glob 按模式搜索文件。"""
    pattern: str = args.get("pattern", "")
    if not pattern:
        return ToolResult.fail("pattern is required")

    search_path: str = args.get("path", ".")
    rg_path: str = args.get("_rg_path", "rg")

    # 如果 pattern 不以 **/ 开头，自动添加以实现递归搜索
    glob_pattern = pattern
    if not glob_pattern.startswith("**/") and not glob_pattern.startswith("/"):
        glob_pattern = f"**/{glob_pattern}"

    rg_args = [
        rg_path,
        "--files",
        "--glob", glob_pattern,
        "--color", "never",
        search_path,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *rg_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=DEFAULT_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ToolResult.fail(f"搜索超时 ({DEFAULT_TIMEOUT_SEC}s)")

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        if proc.returncode == 2:
            return ToolResult.fail(f"ripgrep error: {stderr.strip()}")

        if not stdout.strip():
            return ToolResult.ok(GlobResultData(
                files=[],
                total_count=0,
                pattern=pattern,
                search_path=search_path,
            ))

        # 解析文件路径列表
        all_paths = [line.strip() for line in stdout.strip().split("\n") if line.strip()]
        total_count = len(all_paths)

        # 获取修改时间并排序（降序：最近修改的在前）
        file_entries: list[dict[str, Any]] = []
        for fp in all_paths:
            try:
                mtime = os.path.getmtime(fp)
            except OSError:
                mtime = 0.0
            file_entries.append({"path": fp, "mtime": mtime})

        file_entries.sort(key=lambda x: x["mtime"], reverse=True)

        # 限制返回数量
        file_entries = file_entries[:MAX_FILES]

        return ToolResult.ok(GlobResultData(
            files=file_entries,
            total_count=total_count,
            pattern=pattern,
            search_path=search_path,
        ))

    except FileNotFoundError:
        return ToolResult.fail("ripgrep (rg) 命令不可用，请先安装 ripgrep")
    except OSError as e:
        return ToolResult.fail(f"执行 ripgrep 失败: {e}")


def render_glob_result(result: ToolResult) -> str:
    """格式化 Glob 搜索结果。"""
    if not result.success:
        return f"Error: {result.error}"

    data: GlobResultData = result.data

    if data.total_count == 0:
        return f"No files found matching pattern '{data.pattern}'."

    lines = [f"Found {data.total_count} file(s) matching '{data.pattern}':"]

    shown = min(len(data.files), MAX_FILES)
    for entry in data.files[:shown]:
        lines.append(entry["path"])

    if data.total_count > MAX_FILES:
        lines.append(f"\n... and {data.total_count - MAX_FILES} more files (showing first {MAX_FILES})")

    return "\n".join(lines)
