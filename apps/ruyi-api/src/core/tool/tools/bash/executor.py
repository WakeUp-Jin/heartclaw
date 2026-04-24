"""Bash 工具的执行逻辑与输出格式化。

采用临时文件模式：stdout/stderr 合并写入临时文件，
命令结束后按文件大小决定是全量返回还是截断 + 持久化路径。
render_result 输出长度对齐 OutputTruncator.max_result_chars，
确保不触发调度器的二次裁剪。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.settings import get_heartclaw_home
from core.tool.types import ToolResult
from utils.logger import get_logger

logger = get_logger("tool.bash")

# ── 阈值常量 ──

MAX_INLINE_SIZE = 128 * 1024        # 128KB：超过此大小持久化到磁盘
MAX_RENDER_CHARS = 2000              # 对齐 OutputTruncator.max_result_chars
DEFAULT_TIMEOUT_MS = 120_000         # 默认超时 2 分钟
MAX_TIMEOUT_MS = 10 * 60 * 1000     # 最大超时 10 分钟


def _get_tool_results_dir() -> Path:
    """获取工具输出持久化目录，不存在则创建。"""
    d = get_heartclaw_home() / "tool_results"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _persist_output_file(tmp_path: str) -> tuple[str, int]:
    """将临时输出文件复制到持久化目录，返回 (dest_path, file_size)。"""
    dest_dir = _get_tool_results_dir()
    file_size = os.path.getsize(tmp_path)
    dest_name = f"bash_{int(time.time())}_{os.getpid()}.output"
    dest_path = str(dest_dir / dest_name)
    shutil.copy2(tmp_path, dest_path)
    return dest_path, file_size


@dataclass
class BashResultData:
    """Bash 工具执行结果的结构化数据。"""
    output: str
    exit_code: int
    command: str
    timed_out: bool = False
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    persisted_output_path: str | None = None
    persisted_output_size: int | None = None


async def bash_handler(args: dict[str, Any]) -> ToolResult:
    """执行 bash 命令，stdout + stderr 合并写入临时文件。"""
    command: str = args.get("command", "")
    if not command:
        return ToolResult.fail("command is required")

    timeout_ms: int = args.get("timeout") or DEFAULT_TIMEOUT_MS
    timeout_ms = min(timeout_ms, MAX_TIMEOUT_MS)
    timeout_sec = timeout_ms / 1000.0

    # 1. 创建临时文件
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".bash_output", prefix="hc_")

    try:
        # 2. spawn 子进程，stdout/stderr 都写入临时文件
        with open(tmp_fd, "wb") as tmp_file:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=tmp_file,
                stderr=tmp_file,
                cwd=os.getcwd(),
                env=os.environ.copy(),
            )

            # 3. 等待完成（含超时）
            timed_out = False
            try:
                await asyncio.wait_for(proc.wait(), timeout=timeout_sec)
            except asyncio.TimeoutError:
                timed_out = True
                try:
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    pass

        exit_code = proc.returncode if proc.returncode is not None else -1

        # 4. 读取输出文件，按大小判断
        file_size = os.path.getsize(tmp_path)
        persisted_path: str | None = None
        persisted_size: int | None = None

        if file_size == 0:
            output = ""
        elif file_size <= MAX_INLINE_SIZE:
            with open(tmp_path, "r", encoding="utf-8", errors="replace") as f:
                output = f.read()
        else:
            # 大文件：读取前段，持久化完整文件
            with open(tmp_path, "r", encoding="utf-8", errors="replace") as f:
                output = f.read(MAX_INLINE_SIZE)
            persisted_path, persisted_size = _persist_output_file(tmp_path)
            logger.info(
                "Bash output persisted: %s (%d bytes)", persisted_path, persisted_size,
            )

        return ToolResult.ok(BashResultData(
            output=output.strip() or "(no output)",
            exit_code=exit_code,
            command=command,
            timed_out=timed_out,
            timeout_ms=timeout_ms,
            persisted_output_path=persisted_path,
            persisted_output_size=persisted_size,
        ))

    except OSError as e:
        return ToolResult.fail(f"Failed to execute command: {e}")
    finally:
        # 清理临时文件
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def render_bash_result(result: ToolResult) -> str:
    """格式化 Bash 执行结果，输出长度对齐 OutputTruncator.max_result_chars。

    确保返回的字符串 <= MAX_RENDER_CHARS，这样调度器的
    OutputTruncator.truncate() 不会再触发二次裁剪。
    """
    if not result.success:
        return f"Error: {result.error}"

    data: BashResultData = result.data
    output = data.output

    # 拼接前缀信息
    prefix = ""
    if data.timed_out:
        prefix = f"[timeout after {data.timeout_ms}ms]\n"
    if data.exit_code != 0 and not data.timed_out:
        prefix = f"[exit code: {data.exit_code}]\n"

    available = MAX_RENDER_CHARS - len(prefix)

    # 大输出：前段预览 + 持久化路径
    if data.persisted_output_path:
        notice = (
            f"\n\n[output too large ({data.persisted_output_size} bytes). "
            f"Full output saved to: {data.persisted_output_path}. "
            f"Use ReadFile to view.]"
        )
        preview_len = max(available - len(notice), 200)
        return prefix + output[:preview_len] + notice

    # 小输出：全文返回
    if len(output) <= available:
        return prefix + output

    # 中等输出：前段 + 尾段 + 截断提示
    tail_len = 300
    notice = f"\n\n... [{len(output)} chars, truncated] ...\n\n"
    head_len = max(available - len(notice) - tail_len, 200)
    return prefix + output[:head_len] + notice + output[-tail_len:]
