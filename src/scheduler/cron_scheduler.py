"""定时任务调度器。

每秒扫描 scheduled_tasks.json，到期的任务通过消息队列入队执行。
循环任务从当前时间重新计算下次触发；一次性任务触发后自动删除。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import TYPE_CHECKING

from core.agent.context_vars import current_chat_id
from core.queue.types import QueueMessage, MessagePriority
from scheduler.cron_parser import cron_to_human, next_cron_time
from scheduler.cron_tasks import (
    CronTask,
    mark_fired,
    read_cron_tasks,
    remove_cron_tasks,
)
from utils.logger import get_logger

if TYPE_CHECKING:
    from core.queue.message_queue import MessageQueue

logger = get_logger("cron_scheduler")

CHECK_INTERVAL_S = 1.0
FILE_RELOAD_INTERVAL_S = 5.0


class CronTaskScheduler:
    """asyncio-based cron task scheduler.

    Fires tasks by enqueuing them into the shared MessageQueue,
    which ensures mutual exclusion with user messages and KAIROS ticks.
    """

    def __init__(self, queue: MessageQueue) -> None:
        self._queue = queue
        self._running = False
        self._loop_task: asyncio.Task[None] | None = None

        self._tasks: list[CronTask] = []
        self._next_fire_at: dict[str, float] = {}
        self._last_file_load: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._load_tasks()
        self._loop_task = asyncio.create_task(self._loop())
        logger.info("CronTaskScheduler started")

    async def stop(self) -> None:
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None
        logger.info("CronTaskScheduler stopped")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._check()
            except Exception:
                logger.error("Error in cron check loop", exc_info=True)
            await asyncio.sleep(CHECK_INTERVAL_S)

    async def _check(self) -> None:
        now = time.time()

        if now - self._last_file_load >= FILE_RELOAD_INTERVAL_S:
            self._load_tasks()

        for task in self._tasks:
            nxt = self._next_fire_at.get(task.id)
            if nxt is None:
                continue
            if now < nxt:
                continue

            await self._on_fire(task, now)

    # ------------------------------------------------------------------
    # Fire
    # ------------------------------------------------------------------

    async def _on_fire(self, task: CronTask, now: float) -> None:
        human = cron_to_human(task.cron)
        logger.info(
            "[CronFire] 任务 %s 触发 (%s): %s",
            task.id, human, task.prompt[:80],
        )

        try:
            current_chat_id.set(task.chat_id)
            msg = QueueMessage(
                priority=MessagePriority.CRON,
                mode="cron",
                content=task.prompt,
                chat_id=task.chat_id,
            )
            future = await self._queue.enqueue(msg)
            reply = await future
            logger.info(
                "[CronFire] 任务 %s 完成，回复: %s",
                task.id, reply[:200],
            )
        except Exception:
            logger.error("[CronFire] 任务 %s 执行失败", task.id, exc_info=True)

        if task.recurring:
            new_next = next_cron_time(task.cron, datetime.fromtimestamp(now))
            self._next_fire_at[task.id] = new_next.timestamp() if new_next else float("inf")
            try:
                mark_fired([task.id], now)
            except Exception:
                logger.error("Failed to persist last_fired_at for %s", task.id, exc_info=True)
        else:
            self._next_fire_at.pop(task.id, None)
            try:
                remove_cron_tasks([task.id])
            except Exception:
                logger.error("Failed to remove one-shot task %s", task.id, exc_info=True)

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------

    def _load_tasks(self) -> None:
        self._tasks = read_cron_tasks()
        self._last_file_load = time.time()

        live_ids = {t.id for t in self._tasks}
        for dead_id in list(self._next_fire_at.keys()):
            if dead_id not in live_ids:
                del self._next_fire_at[dead_id]

        for task in self._tasks:
            if task.id not in self._next_fire_at:
                anchor = datetime.fromtimestamp(task.last_fired_at or task.created_at)
                nxt = next_cron_time(task.cron, anchor)
                self._next_fire_at[task.id] = nxt.timestamp() if nxt else float("inf")

        if self._tasks:
            logger.debug(
                "Loaded %d cron task(s), next fires: %s",
                len(self._tasks),
                {tid: datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts != float("inf") else "never"
                 for tid, ts in self._next_fire_at.items()},
            )
