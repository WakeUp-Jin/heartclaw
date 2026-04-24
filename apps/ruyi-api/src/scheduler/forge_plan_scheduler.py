"""锻造计划自省调度器。

每天在可配置时间（默认 23:00）运行一次，调用 forge_plan_agent 分析
近期短期记忆，将锻造计划草案写入 orders/review/ 待用户审核。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

from core.agent.forge_plan_agent import run_forge_plan_analysis
from config.settings import get_heartclaw_home
from utils.logger import get_logger

if TYPE_CHECKING:
    from core.llm.services.base import BaseLLMService
    from storage.short_memory_store import ShortMemoryStore

logger = get_logger("forge_plan_scheduler")


class ForgePlanScheduler:
    """定时触发锻造计划自省，将结果写入 review/ 目录。"""

    def __init__(
        self,
        llm_low: BaseLLMService,
        short_memory_store: ShortMemoryStore,
        schedule_time: str = "23:00",
        recent_days: int = 7,
    ) -> None:
        self._llm = llm_low
        self._short_store = short_memory_store
        self._schedule_time = schedule_time
        self._recent_days = recent_days
        self._scheduler: Any | None = None

    async def start(self) -> None:
        """启动 APScheduler 定时任务。"""
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            logger.warning(
                "apscheduler not installed -- forge plan scheduler disabled. "
                "Install with: pip install apscheduler",
            )
            return

        hour, minute = self._schedule_time.split(":")
        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self._run_analysis,
            CronTrigger(hour=int(hour), minute=int(minute)),
            id="forge_plan_daily",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info(
            "Forge plan scheduler started (daily at %s)", self._schedule_time
        )

    async def stop(self) -> None:
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            logger.info("Forge plan scheduler stopped")

    async def run_now(self) -> dict[str, Any]:
        """手动触发一次自省（用于测试）。"""
        return await self._run_analysis()

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    async def _run_analysis(self) -> dict[str, Any]:
        now = datetime.now()
        logger.info("Starting forge plan analysis at %s", now.isoformat())

        home = get_heartclaw_home()

        result = await run_forge_plan_analysis(
            llm=self._llm,
            short_store=self._short_store,
            heartclaw_home=home,
            recent_days=self._recent_days,
        )

        if not result.has_proposal:
            logger.info("No forge proposal: %s", result.reason)
            return {
                "timestamp": now.isoformat(),
                "has_proposal": False,
                "reason": result.reason,
            }

        review_dir = home / "tiangong" / "orders" / "review"
        review_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{now.strftime('%Y%m%d-%H%M%S')}-{result.tool_name}.md"
        review_path = review_dir / filename

        try:
            review_path.write_text(result.plan_content, encoding="utf-8")
            logger.info("Forge plan written to review: %s", review_path)
        except OSError as e:
            logger.error("Failed to write forge plan: %s", e)
            return {
                "timestamp": now.isoformat(),
                "has_proposal": True,
                "tool_name": result.tool_name,
                "error": str(e),
            }

        return {
            "timestamp": now.isoformat(),
            "has_proposal": True,
            "tool_name": result.tool_name,
            "review_path": str(review_path),
        }
