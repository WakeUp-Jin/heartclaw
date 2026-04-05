"""天工核心引擎 —— 巡查锻造令 + 调度 Coding Agent。

天工不实现任何锻造逻辑（写代码、编译、交付、写说明书）。
所有具体工作由 Coding Agent 按照锻造规范（forge-spec.md）自行完成。
天工只做三件事：巡查、启动、归档。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path

from tiangong.adapters import CodingAgentAdapter, AgentResult

logger = logging.getLogger("tiangong.engine")


class TianGongEngine:
    """天工核心引擎。

    Parameters
    ----------
    config : dict
        必须包含:
        - shared_dir: 共享卷在容器内的路径（映射到宿主机 .pineclaw/）
        - workspace_dir: Rust 工作空间路径
        - poll_interval: 巡查间隔秒数（默认 900 = 15分钟）
        - agent: Coding Agent 适配器配置（含 type 字段）
    """

    def __init__(self, config: dict) -> None:
        self.shared_dir = Path(config["shared_dir"])
        self.workspace = config["workspace_dir"]
        self.poll_interval: int = config.get("poll_interval", 900)

        self.orders_dir = self.shared_dir / "tiangong" / "orders"
        self.forge_spec_path = self.shared_dir / "tiangong" / "forge-spec.md"

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

    async def _forge(self, order_file: Path) -> None:
        """处理一个锻造令：移到 processing → 调 Agent → 归档。"""
        logger.info(
            "Processing order: %s (agent=%s, workspace=%s)",
            order_file.name,
            self.agent.agent_type,
            self.workspace,
        )

        proc_file = self._move_order(order_file, "processing")
        order_content = proc_file.read_text(encoding="utf-8")

        forge_spec = ""
        if self.forge_spec_path.is_file():
            forge_spec = self.forge_spec_path.read_text(encoding="utf-8")

        prompt = f"{forge_spec}\n\n---\n\n# 本次锻造令\n\n{order_content}"

        result = await self.agent.run(prompt)

        self._archive_order(proc_file, result)

        if result.success:
            logger.info("Forge succeeded: %s", order_file.name)
        else:
            logger.error("Forge failed: %s — %s", order_file.name, result.error)

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

    def _ensure_dirs(self) -> None:
        """确保 orders 子目录存在。"""
        for sub in ("pending", "processing", "done"):
            (self.orders_dir / sub).mkdir(parents=True, exist_ok=True)
