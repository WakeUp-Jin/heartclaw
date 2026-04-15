"""天工核心引擎 —— 巡查锻造令 + 调度 Coding Agent。

天工不实现任何锻造逻辑（写代码、编译、交付、写说明书）。
所有具体工作由 Coding Agent 按照锻造规范（forge-spec.md）自行完成。
天工只做四件事：巡查、启动、归档、记录。
"""

from __future__ import annotations

import asyncio
import logging
import platform
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from tiangong.adapters import CodingAgentAdapter, AgentResult

logger = logging.getLogger("tiangong.engine")

_RE_TOOL_NAME = re.compile(
    r"^#\s*(?:锻造令|反馈重锻令)[：:]\s*(.+)", re.MULTILINE
)
_RE_FORGE_TYPE = re.compile(
    r"^-\s*锻造类型[：:]\s*(.+)", re.MULTILINE
)
_RE_ROLLOUT_PATH = re.compile(
    r"^-\s*(?:Codex|Agent)\s*会话记录[：:]\s*(.+)", re.MULTILINE
)


class TianGongEngine:
    """天工核心引擎。

    Parameters
    ----------
    config : dict
        必须包含:
        - shared_dir: 共享卷在容器内的路径（映射到宿主机 .heartclaw/）
        - workspace_dir: Rust 工作空间根路径（各工具在其子目录中工作）
        - poll_interval: 巡查间隔秒数（默认 900 = 15分钟）
        - agent: Coding Agent 适配器配置（含 type 字段）
    """

    def __init__(self, config: dict) -> None:
        self.shared_dir = Path(config["shared_dir"])
        self.workspace = Path(config["workspace_dir"])
        self.poll_interval: int = config.get("poll_interval", 900)

        self.orders_dir = self.shared_dir / "tiangong" / "orders"
        self.forge_spec_path = self.shared_dir / "tiangong" / "forge-spec.md"
        self.forge_logs_dir = self.shared_dir / "tiangong" / "forge-logs"

        self.agent = CodingAgentAdapter.create(config["agent"])

    def validate_runtime(self) -> None:
        """启动前做一次运行环境自检。"""
        self._ensure_dirs()
        logger.info(
            "Validating TianGong runtime: agent=%s, workspace=%s, shared_dir=%s",
            self.agent.agent_type,
            self.workspace,
            self.shared_dir,
        )
        self.agent.validate_environment()

    async def run(self) -> None:
        """主循环：定时巡查。"""
        self._ensure_dirs()
        logger.info(
            "TianGong engine started. agent=%s, poll_interval=%ds, orders=%s",
            self.agent.agent_type,
            self.poll_interval,
            self.orders_dir,
        )
        while True:
            await self._patrol()
            await asyncio.sleep(self.poll_interval)

    # ------------------------------------------------------------------
    # 巡查
    # ------------------------------------------------------------------

    async def _patrol(self) -> None:
        """巡查一轮 pending 目录。"""
        pending_dir = self.orders_dir / "pending"
        orders = sorted(pending_dir.glob("*.md"))

        if not orders:
            logger.debug("No pending orders.")
            return

        logger.info("Found %d pending order(s).", len(orders))
        for order_file in orders:
            await self._forge(order_file)

    # ------------------------------------------------------------------
    # 锻造
    # ------------------------------------------------------------------

    async def _forge(self, order_file: Path) -> None:
        """处理一个锻造令：移到 processing → 调 Agent → 归档 → 写锻造记录。"""
        proc_file = self._move_order(order_file, "processing")
        order_content = proc_file.read_text(encoding="utf-8")

        meta = self._parse_order_meta(order_content)
        tool_name = meta["tool_name"]
        forge_type = meta["forge_type"]
        rollout_path = meta["rollout_path"]

        tool_workspace = self.workspace / tool_name
        tool_workspace.mkdir(parents=True, exist_ok=True)

        logger.info(
            "Processing order: %s (tool=%s, type=%s, agent=%s, cwd=%s)",
            order_file.name, tool_name, forge_type,
            self.agent.agent_type, tool_workspace,
        )

        # 临时将 agent 的 cwd 切到工具子目录
        original_cwd = self.agent.cwd
        self.agent.cwd = str(tool_workspace)
        try:
            result = await self._dispatch_agent(
                order_content, forge_type, rollout_path,
            )
        finally:
            self.agent.cwd = original_cwd

        self._archive_order(proc_file, result)

        done_order_path = self.orders_dir / "done" / proc_file.name
        self._write_forge_log(
            tool_name=tool_name,
            forge_type=forge_type,
            order_path=done_order_path,
            tool_workspace=tool_workspace,
            result=result,
        )

        if result.success:
            logger.info("Forge succeeded: %s", order_file.name)
        else:
            logger.error("Forge failed: %s — %s", order_file.name, result.error)

    async def _dispatch_agent(
        self,
        order_content: str,
        forge_type: str,
        rollout_path: Optional[str],
    ) -> AgentResult:
        """根据锻造类型选择首次执行或恢复会话执行。"""
        forge_spec = ""
        if self.forge_spec_path.is_file():
            forge_spec = self.forge_spec_path.read_text(encoding="utf-8")
        runtime_env = self._build_runtime_env_prompt()

        prompt = (
            f"{forge_spec}\n\n"
            f"{runtime_env}\n\n"
            f"---\n\n"
            f"# 本次锻造令\n\n"
            f"{order_content}"
        )

        is_reforge = forge_type.startswith("重锻")
        if is_reforge and rollout_path:
            logger.info(
                "Reforge mode: resuming from rollout %s", rollout_path
            )
            return await self.agent.run_with_rollout(prompt, rollout_path)

        return await self.agent.run(prompt)

    # ------------------------------------------------------------------
    # 锻造令解析
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_order_meta(content: str) -> dict[str, Optional[str]]:
        """从锻造令 Markdown 中解析元信息。

        提取:
        - tool_name: 从标题 ``# 锻造令：xxx`` 或 ``# 反馈重锻令：xxx``
        - forge_type: 从 ``- 锻造类型：xxx``，默认 ``首次``
        - rollout_path: 从 ``- Agent 会话记录：xxx``（仅重锻令有，兼容旧格式 "Codex 会话记录"）
        """
        tool_name = "unknown-tool"
        m = _RE_TOOL_NAME.search(content)
        if m:
            tool_name = m.group(1).strip()

        forge_type = "首次"
        m = _RE_FORGE_TYPE.search(content)
        if m:
            forge_type = m.group(1).strip()

        rollout_path: Optional[str] = None
        m = _RE_ROLLOUT_PATH.search(content)
        if m:
            val = m.group(1).strip()
            if val and val != "未获取":
                rollout_path = val

        return {
            "tool_name": tool_name,
            "forge_type": forge_type,
            "rollout_path": rollout_path,
        }

    # ------------------------------------------------------------------
    # 归档
    # ------------------------------------------------------------------

    def _move_order(self, order_file: Path, target: str) -> Path:
        """移动锻造令到指定子目录（pending/processing/done）。"""
        target_dir = self.orders_dir / target
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / order_file.name
        shutil.move(str(order_file), str(dest))
        logger.debug("Moved %s → %s/", order_file.name, target)
        return dest

    def _archive_order(self, proc_file: Path, result: AgentResult) -> None:
        """将锻造令归档到 done/，追加结果记录。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "成功" if result.success else "失败"

        appendix = (
            f"\n\n---\n\n"
            f"## 锻造结果\n\n"
            f"- 状态：{status}\n"
            f"- 完成时间：{now}\n"
        )
        if not result.success and result.error:
            appendix += f"- 失败原因：{result.error[:500]}\n"
        if result.output:
            appendix += f"- Agent 输出摘要：{result.output[:500]}\n"

        with open(proc_file, "a", encoding="utf-8") as f:
            f.write(appendix)

        self._move_order(proc_file, "done")

    # ------------------------------------------------------------------
    # 锻造记录
    # ------------------------------------------------------------------

    def _write_forge_log(
        self,
        tool_name: str,
        forge_type: str,
        order_path: Path,
        tool_workspace: Path,
        result: AgentResult,
    ) -> None:
        """创建或更新锻造记录。

        锻造记录是一个简单的 .md 文件，同一工具直接覆盖基本信息，
        但保留并追加锻造历史行。
        """
        self.forge_logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = self.forge_logs_dir / f"{tool_name}.md"

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_text = "已完成" if result.success else "失败"
        status_icon = "✅" if result.success else "❌"

        history = self._load_forge_history(log_file)
        history.append(f"- [{now}] {forge_type} {status_icon}")

        history_block = "\n".join(history)

        content = (
            f"# {tool_name} 锻造记录\n"
            f"\n"
            f"## 基本信息\n"
            f"\n"
            f"- 工具名称：{tool_name}\n"
            f"- 状态：{status_text}\n"
            f"- 最近锻造时间：{now}\n"
            f"\n"
            f"## 文件路径\n"
            f"\n"
            f"- 源码：{tool_workspace}\n"
            f"- 锻造令：{order_path}\n"
            f"- Agent 会话记录：{result.rollout_path or '未获取'}\n"
            f"\n"
            f"## 锻造历史\n"
            f"\n"
            f"{history_block}\n"
        )

        log_file.write_text(content, encoding="utf-8")
        logger.info("Forge log written: %s", log_file)

    @staticmethod
    def _load_forge_history(log_file: Path) -> list[str]:
        """从已有的锻造记录中读取锻造历史行。"""
        if not log_file.is_file():
            return []

        text = log_file.read_text(encoding="utf-8")
        in_history = False
        lines: list[str] = []
        for line in text.splitlines():
            if line.strip() == "## 锻造历史":
                in_history = True
                continue
            if in_history:
                if line.startswith("## "):
                    break
                stripped = line.strip()
                if stripped.startswith("- ["):
                    lines.append(stripped)
        return lines

    # ------------------------------------------------------------------
    # 基础设施
    # ------------------------------------------------------------------

    def _ensure_dirs(self) -> None:
        """确保 orders 子目录和 forge-logs 目录存在。"""
        for sub in ("pending", "processing", "done"):
            (self.orders_dir / sub).mkdir(parents=True, exist_ok=True)
        self.forge_logs_dir.mkdir(parents=True, exist_ok=True)

    def _build_runtime_env_prompt(self) -> str:
        """构建注入到 Prompt 的天工执行环境说明。"""
        cargo_ver = self._probe_version(["cargo", "--version"])
        rustc_ver = self._probe_version(["rustc", "--version"])
        return (
            "## 天工执行环境（自动注入）\n\n"
            f"- 操作系统：{platform.system().lower()}\n"
            f"- 架构：{platform.machine().lower()}\n"
            f"- 工作空间根目录：{self.workspace}\n"
            f"- 共享目录：{self.shared_dir}\n"
            f"- cargo 版本：{cargo_ver}\n"
            f"- rustc 版本：{rustc_ver}\n"
        )

    @staticmethod
    def _probe_version(cmd: list[str]) -> str:
        """探测命令版本，失败时返回可读提示。"""
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except FileNotFoundError:
            return "not found"
        except Exception as exc:  # pragma: no cover
            return f"error: {exc}"

        output = (proc.stdout or proc.stderr).strip()
        if output:
            return output.splitlines()[0]
        return f"exit_code={proc.returncode}"
