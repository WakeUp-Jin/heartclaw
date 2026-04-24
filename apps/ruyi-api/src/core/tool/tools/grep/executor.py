"""Grep 工具的执行逻辑 —— 仅使用 ripgrep 实现。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from core.tool.types import ToolResult
from utils.logger import get_logger

logger = get_logger("tool.grep")

MAX_OUTPUT_CHARS = 100_000
DEFAULT_TIMEOUT_SEC = 30
DEFAULT_MAX_RESULTS = 50


@dataclass
class GrepResultData:
    """Grep 工具执行结果的结构化数据。"""
    output: str
    match_count: int
    pattern: str
    search_path: str


async def grep_handler(args: dict[str, Any]) -> ToolResult:
    """使用 ripgrep 执行正则搜索。"""
    pattern: str = args.get("pattern", "")
    if not pattern:
        return ToolResult.fail("pattern is required")

    search_path: str = args.get("path", ".")
    include: str = args.get("include", "")
    context_lines: int = args.get("context_lines", 0)
    max_results: int = args.get("max_results", DEFAULT_MAX_RESULTS)
    rg_path: str = args.get("_rg_path", "rg")

    # 组装 rg 参数
    rg_args = [
        rg_path,
        "--line-number",
        "--no-heading",
        "--color", "never",
        "--max-count", str(max_results),
    ]

    if context_lines > 0:
        rg_args += ["-C", str(context_lines)]

    if include:
        rg_args += ["--glob", include]

    rg_args += [pattern, search_path]

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

        # rg 退出码: 0=有匹配, 1=无匹配, 2=错误
        if proc.returncode == 2:
            return ToolResult.fail(f"ripgrep error: {stderr.strip()}")

        if proc.returncode == 1 or not stdout.strip():
            return ToolResult.ok(GrepResultData(
                output="No matches found.",
                match_count=0,
                pattern=pattern,
                search_path=search_path,
            ))

        match_count = stdout.count("\n")
        output = stdout.strip()

        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + f"\n\n... [truncated, showing first {MAX_OUTPUT_CHARS} chars]"

        return ToolResult.ok(GrepResultData(
            output=output,
            match_count=match_count,
            pattern=pattern,
            search_path=search_path,
        ))

    except FileNotFoundError:
        return ToolResult.fail("ripgrep (rg) 命令不可用，请先安装 ripgrep")
    except OSError as e:
        return ToolResult.fail(f"执行 ripgrep 失败: {e}")


def render_grep_result(result: ToolResult) -> str:
    """格式化 Grep 搜索结果。"""
    if not result.success:
        return f"Error: {result.error}"

    data: GrepResultData = result.data
    if data.match_count == 0:
        return data.output

    header = f"Found {data.match_count} match(es) for pattern '{data.pattern}':\n\n"
    return header + data.output
