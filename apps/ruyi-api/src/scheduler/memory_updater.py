"""Daily long-term memory update scheduler.

Uses APScheduler to run 4 parallel update agents every day at a
configurable time (default 23:30).  Each agent uses the LOW-tier LLM
to analyse today's short-term records and update one long-term memory file.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

from core.agent.memory_update_agent import run_single_update
from storage.memory_store import VALID_FILES
from utils.logger import get_logger

if TYPE_CHECKING:
    from core.llm.services.base import BaseLLMService
    from storage.memory_store import LocalMemoryStore
    from storage.short_memory_store import ShortMemoryStore

logger = get_logger("memory_updater")


class MemoryUpdateScheduler:
    """Schedules and executes daily long-term memory updates."""

    def __init__(
        self,
        llm_low: BaseLLMService,
        memory_store: LocalMemoryStore,
        short_memory_store: ShortMemoryStore,
        update_log_dir: Path,
        schedule_time: str = "23:30",
    ) -> None:
        self._llm = llm_low
        self._memory_store = memory_store
        self._short_store = short_memory_store
        self._log_dir = update_log_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._schedule_time = schedule_time
        self._scheduler: Any | None = None

    async def start(self) -> None:
        """Start the APScheduler with the daily job."""
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            logger.warning(
                "apscheduler not installed -- memory update scheduler disabled. "
                "Install with: pip install apscheduler",
            )
            return

        hour, minute = self._schedule_time.split(":")
        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self._run_daily_update,
            CronTrigger(hour=int(hour), minute=int(minute)),
            id="memory_daily_update",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info("Memory update scheduler started (daily at %s)", self._schedule_time)

    async def stop(self) -> None:
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            logger.info("Memory update scheduler stopped")

    async def run_now(self) -> dict[str, Any]:
        """Trigger an immediate update (for testing / manual invocation)."""
        return await self._run_daily_update()

    # ------------------------------------------------------------------
    # Core update logic
    # ------------------------------------------------------------------

    async def _run_daily_update(self) -> dict[str, Any]:
        today = date.today()
        logger.info("Starting daily memory update for %s", today.isoformat())

        daily_records = self._short_store.load_daily(today)
        if not daily_records:
            logger.info("No records for today, skipping update")
            return {"date": today.isoformat(), "skipped": True, "reason": "no_records"}

        daily_text = self._records_to_text(daily_records)

        tasks = [
            run_single_update(self._llm, self._memory_store, name, daily_text)
            for name in sorted(VALID_FILES)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        log_entries: list[dict[str, Any]] = []
        for r in results:
            if isinstance(r, BaseException):
                log_entries.append({"error": str(r)})
                logger.error("Update agent failed: %s", r)
            elif isinstance(r, tuple):
                file_name, updated, detail = r
                log_entries.append({
                    "file": file_name,
                    "updated": updated,
                    "detail": detail,
                })

        report = {
            "date": today.isoformat(),
            "timestamp": datetime.now().isoformat(),
            "results": log_entries,
        }

        self._write_update_log(today, report)
        logger.info("Daily memory update complete: %s", report)
        return report

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _records_to_text(records: list[dict[str, Any]]) -> str:
        role_labels = {"user": "用户", "assistant": "助手", "tool": "工具", "system": "系统"}
        lines: list[str] = []
        for item in records:
            role = item.get("role", "?")
            content = item.get("content", "")
            label = role_labels.get(role, role)
            if content:
                lines.append(f"{label}: {content}")
        return "\n".join(lines)

    def _write_update_log(self, today: date, report: dict[str, Any]) -> None:
        log_path = self._log_dir / f"{today.isoformat()}.update.md"
        try:
            lines = [
                f"# 记忆更新日志 {today.isoformat()}",
                f"\n更新时间: {report['timestamp']}\n",
            ]
            for entry in report.get("results", []):
                if "error" in entry:
                    lines.append(f"- **错误**: {entry['error']}")
                else:
                    status = "✅ 已更新" if entry["updated"] else "⏭️ 无变化"
                    lines.append(f"- **{entry['file']}**: {status} — {entry['detail']}")

            log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception as e:
            logger.error("Failed to write update log: %s", e)
