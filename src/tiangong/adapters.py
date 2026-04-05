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
from typing import Optional

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

        stdout, stderr = await proc.communicate()
        code = proc.returncode or 0
        logger.info("Process exited with code %d", code)
        return code, stdout.decode(), stderr.decode()


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
    选项: --full-auto --json
    session 恢复: codex exec resume --last "follow-up"
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)

    @property
    def command_name(self) -> str:
        return "codex"

    async def run(self, prompt: str) -> AgentResult:
        code, stdout, stderr = await self._exec(
            ["codex", "exec", "--full-auto", "--json", prompt],
            cwd=self.cwd,
        )
        if code == 0:
            return AgentResult(success=True, output=stdout)
        return AgentResult(success=False, error=stderr or stdout)

    async def resume(self, message: str) -> AgentResult:
        code, stdout, stderr = await self._exec(
            ["codex", "exec", "resume", "--last", message],
            cwd=self.cwd,
        )
        if code == 0:
            return AgentResult(success=True, output=stdout)
        return AgentResult(success=False, error=stderr or stdout)
