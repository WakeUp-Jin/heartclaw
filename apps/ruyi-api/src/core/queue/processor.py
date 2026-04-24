"""队列处理器 — 串行消费队列消息，尾递归调度 KAIROS tick。

处理流程：
  dequeue → dispatch → 尾部调度
    - user/cron 消息处理完 → 队列空 → 立即注入 tick（不 sleep）
    - tick 消息处理完 → 可中断 sleep → 队列仍空 → 注入下一个 tick
    - sleep 期间有新消息入队 → wake_event 触发 → 跳过 tick，回到 dequeue
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Protocol, TYPE_CHECKING

from config.settings import KairosConfig
from core.output.types import FinalReplyEvent, KairosLifecycleEvent
from core.queue.types import QueueMessage, MessagePriority
from utils.logger import get_logger

if TYPE_CHECKING:
    from core.output.emitter import OutputEmitter

logger = get_logger("queue_processor")

MAX_CONSECUTIVE_TICK_ERRORS = 5
TICK_ERROR_COOLDOWN_S = 60.0
STARTUP_DELAY_S = 5.0


class TickHandler(Protocol):
    """KairosRunner 需要实现的协议。"""

    async def handle_tick(self, msg: QueueMessage) -> str: ...
    def get_sleep_seconds(self, result_text: str) -> int: ...


class AgentRunner(Protocol):
    """Agent 需要实现的协议。"""

    async def run(self, user_text: str, chat_id: str, open_id: str) -> str: ...


class QueueProcessor:
    """从 MessageQueue 串行取出消息并分发执行。

    同一时间只有一个 Agent.run() 或 KairosRunner.handle_tick() 在执行，
    天然互斥，无需额外锁。

    KAIROS 尾递归调度：每条消息处理完后，如果 KAIROS 已启用且队列为空，
    自动注入下一个 tick，无需外部 KairosLoop。
    """

    def __init__(
        self,
        queue: Any,
        agent: AgentRunner,
        emitter: OutputEmitter,
        kairos_runner: TickHandler | None = None,
        kairos_config: KairosConfig | None = None,
    ) -> None:
        self._queue = queue
        self._agent = agent
        self._emitter = emitter
        self._kairos = kairos_runner
        self._kairos_config = kairos_config
        self._running = False
        self._consecutive_tick_errors = 0

    @property
    def _kairos_enabled(self) -> bool:
        return self._kairos is not None and self._kairos_config is not None

    async def run(self) -> None:
        """主循环：dequeue → dispatch → 尾部调度 → 回到 dequeue。"""
        self._running = True
        logger.info("QueueProcessor started")

        if self._kairos_enabled:
            await asyncio.sleep(STARTUP_DELAY_S)
            logger.info(
                "KAIROS tail-dispatch enabled, injecting first tick after %.0fs delay",
                STARTUP_DELAY_S,
            )
            if not self._queue.has_pending():
                await self._inject_tick()

        while self._running:
            msg = await self._queue.dequeue()
            result_text = ""
            tick_failed = False
            try:
                if msg.mode == "tick":
                    await self._emit_kairos("tick_start")

                result_text = await self._dispatch(msg)

                source = "kairos" if msg.mode == "tick" else "ruyi"
                event = FinalReplyEvent(
                    source=source,
                    text=result_text,
                    mode=msg.mode,
                    chat_id=msg.chat_id,
                    open_id=msg.open_id,
                    source_channel=msg.source_channel,
                    source_msg_id=msg.id,
                    _future=msg._future,
                )
                await self._emitter.emit(event)

                if msg.mode == "tick":
                    await self._emit_kairos(
                        "tick_done",
                        {"result_preview": result_text[:200]},
                    )
                    self._consecutive_tick_errors = 0
            except Exception as exc:
                logger.error(
                    "Error processing [%s] id=%s: %s",
                    msg.mode, msg.id, exc, exc_info=True,
                )
                if msg._future and not msg._future.done():
                    msg._future.set_exception(exc)
                if msg.mode == "tick":
                    tick_failed = True
                    self._consecutive_tick_errors += 1
                    if self._consecutive_tick_errors >= MAX_CONSECUTIVE_TICK_ERRORS:
                        logger.warning(
                            "Tick error circuit breaker: %d consecutive failures, "
                            "cooling down %.0fs",
                            self._consecutive_tick_errors, TICK_ERROR_COOLDOWN_S,
                        )
                        await asyncio.sleep(TICK_ERROR_COOLDOWN_S)
                        self._consecutive_tick_errors = 0

            await self._tail_dispatch(msg, result_text, tick_failed)

    async def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Message dispatch
    # ------------------------------------------------------------------

    async def _dispatch(self, msg: QueueMessage) -> str:
        logger.info(
            "Dispatching [%s] id=%s content=%.80s",
            msg.mode, msg.id, msg.content,
        )

        if msg.mode == "tick":
            if self._kairos is None:
                return ""
            return await self._kairos.handle_tick(msg)

        return await self._agent.run(msg.content, msg.chat_id, msg.open_id)

    # ------------------------------------------------------------------
    # KAIROS tail-recursive dispatch
    # ------------------------------------------------------------------

    async def _tail_dispatch(
        self, msg: QueueMessage, result_text: str, tick_failed: bool,
    ) -> None:
        """每条消息处理完后的尾部调度逻辑。

        - user/cron 完成后：队列空 → 立即注入 tick
        - tick 完成后：可中断 sleep → 队列仍空 → 注入 tick
        - tick 失败后：用默认 sleep 时长再试
        """
        if not self._kairos_enabled:
            return

        assert self._kairos_config is not None

        if msg.mode in ("user", "cron"):
            if not self._queue.has_pending():
                logger.debug("Queue empty after %s message, injecting tick immediately", msg.mode)
                await self._inject_tick()
            return

        if msg.mode == "tick":
            if tick_failed:
                sleep_seconds = self._kairos_config.default_sleep_seconds
            else:
                sleep_seconds = self._kairos.get_sleep_seconds(result_text)  # type: ignore[union-attr]

            interrupted = await self._interruptible_sleep(sleep_seconds)
            if interrupted:
                logger.debug("Sleep interrupted, skipping tick injection")
                return

            if not self._queue.has_pending():
                await self._inject_tick()

    async def _inject_tick(self) -> None:
        """构造一条 tick 消息并入队。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tick_content = f"<tick>{now}</tick>"
        msg = QueueMessage(
            priority=MessagePriority.TICK,
            mode="tick",
            content=tick_content,
        )
        await self._queue.enqueue(msg)
        logger.debug("Tick injected: %s", msg.id)

    async def _interruptible_sleep(self, seconds: float) -> bool:
        """可被中断的 sleep。返回 True 表示被中断（有新消息入队）。"""
        assert self._kairos_config is not None
        seconds = max(
            self._kairos_config.min_sleep_seconds,
            min(seconds, self._kairos_config.max_sleep_seconds),
        )
        logger.debug("KAIROS sleeping for %ds", seconds)

        await self._emit_kairos("sleep_start", {"sleep_seconds": seconds})

        self._queue.wake_event.clear()
        try:
            await asyncio.wait_for(
                self._queue.wake_event.wait(),
                timeout=seconds,
            )
            logger.debug("KAIROS sleep interrupted by incoming message")
            await self._emit_kairos("sleep_interrupted")
            return True
        except asyncio.TimeoutError:
            await self._emit_kairos("sleep_done", {"slept_seconds": seconds})
            return False

    # ------------------------------------------------------------------
    # Kairos lifecycle events
    # ------------------------------------------------------------------

    async def _emit_kairos(self, event_name: str, detail: dict | None = None) -> None:
        await self._emitter.emit(KairosLifecycleEvent(
            source="kairos",
            event=event_name,
            detail=detail or {},
        ))
