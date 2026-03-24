"""Bash 工具的执行逻辑与输出格式化。"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Any

from core.tool.types import ToolResult

MAX_OUTPUT_CHARS = 100_000
DEFAULT_TIMEOUT = 30


@dataclass
class BashResultData:
    output: str
    exit_code: int
    command: str
    timed_out: bool = False


async def bash_handler(args: dict[str, Any]) -> ToolResult:
    """执行 bash 命令，返回 stdout + stderr。"""
    command: str = args.get("command", "")
    if not command:
        return ToolResult.fail("command is required")

    timeout: int = args.get("timeout") or DEFAULT_TIMEOUT

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.getcwd(),
            env=os.environ.copy(),
        )

        output = result.stdout
        if result.stderr:
            if output:
                output += "\n"
            output += f"[stderr]:\n{result.stderr}"

        return ToolResult.ok(BashResultData(
            output=output.strip() or "(no output)",
            exit_code=result.returncode,
            command=command,
        ))

    except subprocess.TimeoutExpired:
        return ToolResult.ok(BashResultData(
            output=f"Command timed out after {timeout}s",
            exit_code=-1,
            command=command,
            timed_out=True,
        ))
    except OSError as e:
        return ToolResult.fail(f"Failed to execute command: {e}")


def render_bash_result(result: ToolResult) -> str:
    """格式化 Bash 执行结果供 LLM 阅读。"""
    if not result.success:
        return f"Error: {result.error}"

    data: BashResultData = result.data
    output = data.output

    if len(output) > MAX_OUTPUT_CHARS:
        half = MAX_OUTPUT_CHARS // 2
        output = output[:half] + "\n\n... [truncated] ...\n\n" + output[-half:]

    if data.timed_out:
        return f"[timeout after {DEFAULT_TIMEOUT}s]\n{output}"

    if data.exit_code != 0:
        return f"{output}\n[exit code: {data.exit_code}]"

    return output
