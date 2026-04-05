"""Coding Agent CLI 适配器。

适配器模式解耦天工与具体 CLI 工具。每种 CLI 实现一个子类，
天工通过适配器统一调用，切换 Coding Agent 只需改配置文件。

接入新的 Coding Agent CLI 时，需要：
1. 继承 CodingAgentAdapter
2. 实现 run() 和 resume()
3. 在 create() 工厂方法中注册
4. 查阅该 CLI 的非交互模式文档
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("tiangong.adapters")


@dataclass
class AgentResult:
    """Coding Agent 执行结果。"""

    success: bool
    output: str = ""
    session_id: Optional[str] = None
    error: Optional[str] = None


class CodingAgentAdapter(ABC):
    """Coding Agent CLI 适配器基类。"""

    def __init__(self, config: dict) -> None:
        self.cwd: str = config["workspace_dir"]
        self.agent_type: str = config["type"]

    @abstractmethod
    async def run(self, prompt: str) -> AgentResult:
        """首次执行任务。"""

    @abstractmethod
    async def resume(self, message: str) -> AgentResult:
        """恢复 session 继续执行（多轮交互场景）。"""

    @property
    @abstractmethod
    def command_name(self) -> str:
        """CLI 命令名。"""

    @staticmethod
    def create(config: dict) -> CodingAgentAdapter:
        """工厂方法：根据配置创建对应适配器。"""
        agent_type = config["type"]
        adapters: dict[str, type[CodingAgentAdapter]] = {
            "claude_code": ClaudeCodeAdapter,
            "codex": CodexAdapter,
        }
        cls = adapters.get(agent_type)
        if not cls:
            raise ValueError(
                f"不支持的 Agent 类型: {agent_type}，"
                f"可选: {list(adapters.keys())}"
            )
        return cls(config)

    def validate_environment(self) -> None:
        """启动时校验工作目录和 CLI 是否可用。"""
        cwd_path = Path(self.cwd)
        if not cwd_path.exists():
            raise RuntimeError(
                f"selected agent={self.agent_type} but workspace does not exist: "
                f"{self.cwd}"
            )

        binary_path = shutil.which(self.command_name)
        if not binary_path:
            raise RuntimeError(
                f"selected agent={self.agent_type} but binary "
                f"`{self.command_name}` was not found in PATH"
            )

        logger.info(
            "Agent runtime validated: agent=%s, binary=%s, cwd=%s",
            self.agent_type,
            binary_path,
            self.cwd,
        )

    async def _exec(self, cmd: list[str], cwd: str) -> tuple[int, str, str]:
        """通用子进程执行。返回 (exit_code, stdout, stderr)。"""
        logger.info("Executing agent command: %s (cwd=%s)", " ".join(cmd[:4]), cwd)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            error = (
                f"Agent CLI `{cmd[0]}` not found in PATH. "
                f"selected agent={self.agent_type}"
            )
            logger.error("%s (cwd=%s)", error, cwd)
            return 127, "", error

        stdout_task = asyncio.create_task(
            self._read_stream(proc.stdout, "stdout", logger.info)
        )
        stderr_task = asyncio.create_task(
            self._read_stream(proc.stderr, "stderr", logger.warning)
        )
        await proc.wait()
        stdout = await stdout_task
        stderr = await stderr_task
        code = proc.returncode or 0
        logger.info("Process exited with code %d", code)
        return code, stdout, stderr

    async def _read_stream(
        self,
        stream: asyncio.StreamReader | None,
        stream_name: str,
        log_fn: Callable[..., None],
    ) -> str:
        """逐行读取子进程输出并实时写入日志。"""
        if stream is None:
            return ""

        chunks: list[bytes] = []
        while True:
            line = await stream.readline()
            if not line:
                break
            chunks.append(line)
            text = line.decode(errors="replace").rstrip()
            if text:
                log_fn("[%s][%s] %s", self.agent_type, stream_name, text)

        return b"".join(chunks).decode(errors="replace")


class ClaudeCodeAdapter(CodingAgentAdapter):
    """Claude Code CLI 适配器。

    文档: https://code.claude.com/docs/en/cli-reference
    非交互模式: claude -p "prompt"
    输出格式: --output-format json (含 session_id)
    session 恢复: claude --continue -p "follow-up"
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)

    @property
    def command_name(self) -> str:
        return "claude"

    async def run(self, prompt: str) -> AgentResult:
        code, stdout, stderr = await self._exec(
            ["claude", "-p", "--output-format", "json", prompt],
            cwd=self.cwd,
        )
        return self._parse(code, stdout, stderr)

    async def resume(self, message: str) -> AgentResult:
        code, stdout, stderr = await self._exec(
            ["claude", "--continue", "-p", "--output-format", "json", message],
            cwd=self.cwd,
        )
        return self._parse(code, stdout, stderr)

    @staticmethod
    def _parse(code: int, stdout: str, stderr: str) -> AgentResult:
        if code == 0:
            try:
                data = json.loads(stdout)
                return AgentResult(
                    success=True,
                    output=data.get("result", stdout),
                    session_id=data.get("session_id"),
                )
            except json.JSONDecodeError:
                return AgentResult(success=True, output=stdout)
        return AgentResult(success=False, error=stderr or stdout)


class CodexAdapter(CodingAgentAdapter):
    """OpenAI Codex CLI 适配器。

    文档: https://developers.openai.com/codex/cli/reference/
    非交互模式: codex exec "prompt"
    选项: --dangerously-bypass-approvals-and-sandbox --json
    session 恢复: codex exec resume --last "follow-up"
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)

    @property
    def command_name(self) -> str:
        return "codex"

    async def run(self, prompt: str) -> AgentResult:
        code, stdout, stderr = await self._exec(
            [
                "codex",
                "exec",
                "--dangerously-bypass-approvals-and-sandbox",
                "--json",
                prompt,
            ],
            cwd=self.cwd,
        )
        return self._parse_result(code, stdout, stderr)

    async def resume(self, message: str) -> AgentResult:
        code, stdout, stderr = await self._exec(
            [
                "codex",
                "exec",
                "--dangerously-bypass-approvals-and-sandbox",
                "--json",
                "resume",
                "--last",
                message,
            ],
            cwd=self.cwd,
        )
        return self._parse_result(code, stdout, stderr)

    @classmethod
    def _parse_result(cls, code: int, stdout: str, stderr: str) -> AgentResult:
        if code != 0:
            return AgentResult(success=False, error=stderr or stdout)

        failed_items, has_successful_file_change = cls._inspect_json_events(stdout)
        if failed_items and not has_successful_file_change:
            return AgentResult(
                success=False,
                output=stdout,
                error=cls._summarize_failed_items(failed_items),
            )
        return AgentResult(success=True, output=stdout)

    @staticmethod
    def _inspect_json_events(stdout: str) -> tuple[list[dict], bool]:
        failed_items: list[dict] = []
        has_successful_file_change = False

        for line in stdout.splitlines():
            text = line.strip()
            if not text or not text.startswith("{"):
                continue
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                continue

            if event.get("type") != "item.completed":
                continue

            item = event.get("item")
            if not isinstance(item, dict):
                continue

            item_type = item.get("type")
            status = item.get("status")

            if item_type == "file_change" and status == "completed":
                has_successful_file_change = True
            if item_type in {"command_execution", "file_change"} and status == "failed":
                failed_items.append(item)

        return failed_items, has_successful_file_change

    @staticmethod
    def _summarize_failed_items(failed_items: list[dict]) -> str:
        first = failed_items[0]
        item_type = first.get("type", "unknown")
        command = first.get("command", "")
        exit_code = first.get("exit_code")
        output = (first.get("aggregated_output") or "").strip().replace("\n", " ")

        parts = [f"codex item failed: type={item_type}"]
        if command:
            parts.append(f"command={command}")
        if exit_code is not None:
            parts.append(f"exit_code={exit_code}")
        if output:
            parts.append(f"output={output[:300]}")

        return ", ".join(parts)
