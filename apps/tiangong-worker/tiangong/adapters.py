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
import os
import signal
import shutil
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("tiangong.adapters")


@dataclass
class AgentResult:
    """Coding Agent 执行结果。"""

    success: bool
    output: str = ""
    session_id: Optional[str] = None
    rollout_path: Optional[str] = None
    error: Optional[str] = None


class CodingAgentAdapter(ABC):
    """Coding Agent CLI 适配器基类。"""

    def __init__(self, config: dict) -> None:
        self.cwd: str = config["workspace_dir"]
        self.agent_type: str = config["type"]
        self._current_proc: asyncio.subprocess.Process | None = None
        self.output_log_path: Path | None = None
        self.on_output: Callable[[str, str], None] | None = None

    @abstractmethod
    async def run(self, prompt: str) -> AgentResult:
        """首次执行任务。"""

    @abstractmethod
    async def resume(self, message: str) -> AgentResult:
        """恢复 session 继续执行（多轮交互场景）。"""

    @abstractmethod
    async def run_with_rollout(
        self, prompt: str, rollout_path: str
    ) -> AgentResult:
        """基于历史会话记录恢复上下文后执行（重锻场景）。"""

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
            "kimi": KimiCliAdapter,
            "opencode": OpenCodeAdapter,
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
                start_new_session=True,
            )
        except FileNotFoundError:
            error = (
                f"Agent CLI `{cmd[0]}` not found in PATH. "
                f"selected agent={self.agent_type}"
            )
            logger.error("%s (cwd=%s)", error, cwd)
            return 127, "", error

        self._current_proc = proc
        stdout_task = asyncio.create_task(
            self._read_stream(proc.stdout, "stdout", logger.info)
        )
        stderr_task = asyncio.create_task(
            self._read_stream(proc.stderr, "stderr", logger.warning)
        )
        try:
            await proc.wait()
            stdout = await stdout_task
            stderr = await stderr_task
            code = proc.returncode or 0
            logger.info("Process exited with code %d", code)
            return code, stdout, stderr
        finally:
            self._current_proc = None

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
                self._append_output_log(stream_name, text)
                if self.on_output is not None:
                    self.on_output(stream_name, text)

        return b"".join(chunks).decode(errors="replace")

    async def cancel_current_run(self, reason: str) -> bool:
        """取消当前正在运行的 Agent 子进程。"""
        proc = self._current_proc
        if proc is None or proc.returncode is not None:
            logger.info("No running agent process to cancel: %s", reason)
            return False

        logger.warning(
            "Cancelling agent process pid=%s agent=%s reason=%s",
            proc.pid,
            self.agent_type,
            reason,
        )
        self._terminate_process(proc)
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
            return True
        except asyncio.TimeoutError:
            logger.warning("Agent process did not exit after terminate; killing pid=%s", proc.pid)
            self._kill_process(proc)
            await proc.wait()
            return True

    def _append_output_log(self, stream_name: str, text: str) -> None:
        if self.output_log_path is None:
            return

        try:
            self.output_log_path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
            with open(self.output_log_path, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} [{stream_name}] {text}\n")
        except OSError:
            logger.warning(
                "Failed to append agent output log: %s",
                self.output_log_path,
                exc_info=True,
            )

    @staticmethod
    def _terminate_process(proc: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            proc.terminate()

    @staticmethod
    def _kill_process(proc: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            proc.kill()


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

    async def run_with_rollout(
        self, prompt: str, rollout_path: str
    ) -> AgentResult:
        # Claude Code 不使用 rollout 机制，退化为 --continue
        return await self.resume(prompt)

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

    async def run_with_rollout(
        self, prompt: str, rollout_path: str
    ) -> AgentResult:
        code, stdout, stderr = await self._exec(
            [
                "codex",
                "exec",
                "--resume-rollout", rollout_path,
                "--dangerously-bypass-approvals-and-sandbox",
                "--json",
                prompt,
            ],
            cwd=self.cwd,
        )
        return self._parse_result(code, stdout, stderr)

    @classmethod
    def _parse_result(cls, code: int, stdout: str, stderr: str) -> AgentResult:
        if code != 0:
            return AgentResult(success=False, error=stderr or stdout)

        failed_items, has_successful_file_change, thread_id = (
            cls._inspect_json_events(stdout)
        )

        rollout_path: Optional[str] = None
        if thread_id:
            rollout_path = cls._find_rollout_path(thread_id)

        if failed_items and not has_successful_file_change:
            return AgentResult(
                success=False,
                output=stdout,
                session_id=thread_id,
                rollout_path=rollout_path,
                error=cls._summarize_failed_items(failed_items),
            )
        return AgentResult(
            success=True,
            output=stdout,
            session_id=thread_id,
            rollout_path=rollout_path,
        )

    @staticmethod
    def _inspect_json_events(
        stdout: str,
    ) -> tuple[list[dict], bool, Optional[str]]:
        """解析 Codex JSON 事件流。

        返回 (failed_items, has_successful_file_change, thread_id)。
        thread_id 从 ``thread.started`` 事件中提取，用于定位 rollout 文件。
        """
        failed_items: list[dict] = []
        has_successful_file_change = False
        thread_id: Optional[str] = None

        for line in stdout.splitlines():
            text = line.strip()
            if not text or not text.startswith("{"):
                continue
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")

            if event_type == "thread.started":
                thread_id = event.get("thread_id")
                continue

            if event_type != "item.completed":
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

        return failed_items, has_successful_file_change, thread_id

    @staticmethod
    def _find_rollout_path(thread_id: str) -> Optional[str]:
        """根据 thread_id 在 ~/.codex/sessions/ 下查找 rollout 文件。

        Codex 将会话记录存储为:
        ~/.codex/sessions/YYYY/MM/DD/rollout-TIMESTAMP-THREAD_ID_PREFIX.jsonl
        文件名中包含 thread_id 的前 8 位。
        """
        sessions_dir = Path.home() / ".codex" / "sessions"
        if not sessions_dir.is_dir():
            logger.debug("Codex sessions dir not found: %s", sessions_dir)
            return None

        prefix = thread_id[:8]
        matches = list(sessions_dir.rglob(f"*{prefix}*.jsonl"))
        if not matches:
            logger.warning(
                "No rollout file found for thread_id=%s in %s",
                thread_id, sessions_dir,
            )
            return None

        result = str(sorted(matches)[-1])
        logger.info("Found rollout file: %s (thread_id=%s)", result, thread_id)
        return result

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


class KimiCliAdapter(CodingAgentAdapter):
    """Kimi Code CLI 适配器。

    文档: https://moonshotai.github.io/kimi-cli/
    非交互模式: kimi --print -p "prompt"
    输出格式: --output-format stream-json (JSONL)
    session 恢复: kimi --session <ID> --print -p "follow-up"

    Session 管理策略: 调用前用 uuid4 预先生成 session_id 并通过
    ``--session`` 传给 kimi-cli（该参数支持"不存在则创建"语义），
    从而在整个适配器生命周期内持有确定的 session 标识。
    """

    RETRYABLE_EXIT_CODE = 75

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._session_id: Optional[str] = None

    @property
    def command_name(self) -> str:
        return "kimi"

    def _build_cmd(self, prompt: str, session_id: str) -> list[str]:
        return [
            "kimi", "--print",
            "--output-format", "stream-json",
            "--session", session_id,
            "-w", self.cwd,
            "-p", prompt,
        ]

    async def run(self, prompt: str) -> AgentResult:
        self._session_id = str(uuid.uuid4())
        code, stdout, stderr = await self._exec(
            self._build_cmd(prompt, self._session_id),
            cwd=self.cwd,
        )
        return self._parse_result(code, stdout, stderr, self._session_id)

    async def resume(self, message: str) -> AgentResult:
        sid = self._session_id or str(uuid.uuid4())
        self._session_id = sid
        code, stdout, stderr = await self._exec(
            self._build_cmd(message, sid),
            cwd=self.cwd,
        )
        return self._parse_result(code, stdout, stderr, sid)

    async def run_with_rollout(
        self, prompt: str, rollout_path: str
    ) -> AgentResult:
        # kimi-cli 没有 rollout 文件机制；rollout_path 在 kimi 场景下
        # 存储的是上次的 session_id，直接用 --session 恢复上下文。
        session_to_resume = rollout_path or self._session_id or str(uuid.uuid4())
        self._session_id = session_to_resume
        code, stdout, stderr = await self._exec(
            self._build_cmd(prompt, session_to_resume),
            cwd=self.cwd,
        )
        return self._parse_result(code, stdout, stderr, session_to_resume)

    @classmethod
    def _parse_result(
        cls, code: int, stdout: str, stderr: str, session_id: str,
    ) -> AgentResult:
        if code == cls.RETRYABLE_EXIT_CODE:
            return AgentResult(
                success=False,
                output=stdout,
                session_id=session_id,
                rollout_path=session_id,
                error=f"kimi-cli transient error (exit_code=75): {stderr or stdout}"[:500],
            )
        if code != 0:
            return AgentResult(
                success=False,
                output=stdout,
                session_id=session_id,
                rollout_path=session_id,
                error=stderr or stdout,
            )

        last_assistant_content = cls._extract_last_assistant_content(stdout)
        return AgentResult(
            success=True,
            output=last_assistant_content or stdout,
            session_id=session_id,
            rollout_path=session_id,
        )

    @staticmethod
    def _extract_last_assistant_content(stdout: str) -> Optional[str]:
        """从 kimi-cli JSONL 输出中提取最后一条 assistant message 的 content。

        kimi-cli ``--output-format stream-json`` 输出格式::

            {"role":"assistant","content":"...","tool_calls":[...]}
            {"role":"tool","tool_call_id":"tc_1","content":"..."}
            {"role":"assistant","content":"最终结果文本"}
        """
        last_content: Optional[str] = None
        for line in stdout.splitlines():
            text = line.strip()
            if not text or not text.startswith("{"):
                continue
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                continue
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content")
            if isinstance(content, str) and content:
                last_content = content
        return last_content


class OpenCodeAdapter(CodingAgentAdapter):
    """OpenCode CLI 适配器。

    文档: https://open-code.ai/docs/en/cli
    非交互模式: opencode run "prompt"
    输出格式: --format json (JSONL 事件流)
    session 恢复: opencode run --session <ID> "follow-up"
               或 opencode run --continue "follow-up"

    Session 管理策略: 从 JSONL 事件流的 step_start 事件中提取 sessionID
    （格式 ses_XXX），用于后续 --session 恢复上下文。rollout_path 字段
    存储 sessionID，与 KimiCliAdapter 策略一致。
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._session_id: Optional[str] = None

    @property
    def command_name(self) -> str:
        return "opencode"

    async def run(self, prompt: str) -> AgentResult:
        code, stdout, stderr = await self._exec(
            ["opencode", "run", "--format", "json", prompt],
            cwd=self.cwd,
        )
        return self._parse_result(code, stdout, stderr)

    async def resume(self, message: str) -> AgentResult:
        cmd = ["opencode", "run", "--format", "json"]
        if self._session_id:
            cmd.extend(["--session", self._session_id])
        else:
            cmd.append("--continue")
        cmd.append(message)
        code, stdout, stderr = await self._exec(cmd, cwd=self.cwd)
        return self._parse_result(code, stdout, stderr)

    async def run_with_rollout(
        self, prompt: str, rollout_path: str
    ) -> AgentResult:
        session_to_resume = rollout_path or self._session_id
        cmd = ["opencode", "run", "--format", "json"]
        if session_to_resume:
            cmd.extend(["--session", session_to_resume])
        else:
            cmd.append("--continue")
        cmd.append(prompt)
        code, stdout, stderr = await self._exec(cmd, cwd=self.cwd)
        return self._parse_result(code, stdout, stderr)

    def _parse_result(
        self, code: int, stdout: str, stderr: str,
    ) -> AgentResult:
        session_id, text_parts, errors, has_tool_failure = (
            self._inspect_jsonl_events(stdout)
        )
        if session_id:
            self._session_id = session_id

        if code != 0 and not text_parts:
            return AgentResult(
                success=False,
                output=stdout,
                session_id=session_id,
                rollout_path=session_id,
                error=self._build_error_message(errors, stderr, stdout),
            )

        if errors:
            return AgentResult(
                success=False,
                output="\n".join(text_parts) or stdout,
                session_id=session_id,
                rollout_path=session_id,
                error=self._build_error_message(errors, stderr, stdout),
            )

        return AgentResult(
            success=True,
            output="\n".join(text_parts) or stdout,
            session_id=session_id,
            rollout_path=session_id,
        )

    @staticmethod
    def _inspect_jsonl_events(
        stdout: str,
    ) -> tuple[Optional[str], list[str], list[str], bool]:
        """解析 OpenCode JSONL 事件流。

        返回 (session_id, text_parts, errors, has_tool_failure)。

        事件类型:
        - step_start: 含 sessionID
        - text: 模型文本输出（part.text）
        - tool_use: 工具执行（检查 part.state.status）
        - step_finish: 步骤结束（reason="stop" 为最终）
        - error: 错误事件
        """
        session_id: Optional[str] = None
        text_parts: list[str] = []
        errors: list[str] = []
        has_tool_failure = False

        for line in stdout.splitlines():
            text = line.strip()
            if not text or not text.startswith("{"):
                continue
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")

            if event_type == "step_start":
                sid = event.get("sessionID")
                if sid:
                    session_id = sid
                continue

            if event_type == "text":
                part = event.get("part", {})
                content = part.get("text", "")
                if content:
                    text_parts.append(content)
                continue

            if event_type == "tool_use":
                part = event.get("part", {})
                state = part.get("state", {})
                if state.get("status") == "failed":
                    has_tool_failure = True
                    tool_name = part.get("tool", "unknown")
                    output = state.get("output", "")
                    metadata = state.get("metadata", {})
                    exit_code = metadata.get("exit")
                    desc = state.get("title", "")
                    err_parts = [f"tool={tool_name}"]
                    if desc:
                        err_parts.append(f"title={desc}")
                    if exit_code is not None:
                        err_parts.append(f"exit_code={exit_code}")
                    if output:
                        err_parts.append(f"output={output[:300]}")
                    errors.append(", ".join(err_parts))
                continue

            if event_type == "error":
                err_data = event.get("error", {})
                err_name = err_data.get("name", "UnknownError")
                err_msg = (err_data.get("data") or {}).get("message", "")
                errors.append(f"{err_name}: {err_msg}" if err_msg else err_name)
                continue

        return session_id, text_parts, errors, has_tool_failure

    @staticmethod
    def _build_error_message(
        errors: list[str], stderr: str, stdout: str,
    ) -> str:
        if errors:
            return "; ".join(errors)[:500]
        if stderr:
            return stderr[:500]
        return stdout[:500]
