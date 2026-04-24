"""审批等待存储 —— 桥接 ToolScheduler 与飞书卡片回传交互回调。

通过 asyncio.Future 实现跨协程的异步等待:
  - Scheduler 侧: await store.wait_for_approval(call_id)
  - HTTP 回调侧: store.resolve_approval(call_id, outcome)
"""

from __future__ import annotations

import asyncio
from typing import Literal

from utils.logger import logger

ApprovalOutcome = Literal["approve", "cancel", "timeout"]

_DEFAULT_TIMEOUT = 120.0  # 秒


class ApprovalStore:
    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[ApprovalOutcome]] = {}

    async def wait_for_approval(
        self, call_id: str, timeout: float = _DEFAULT_TIMEOUT
    ) -> ApprovalOutcome:
        """创建 Future 并阻塞等待用户审批结果。

        超时后自动返回 ``"timeout"``，不会永远挂起。
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ApprovalOutcome] = loop.create_future()
        self._pending[call_id] = future

        try:
            outcome = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Approval timeout for call_id=%s", call_id)
            outcome = "timeout"
        finally:
            self._pending.pop(call_id, None)

        return outcome

    def resolve_approval(self, call_id: str, outcome: ApprovalOutcome) -> bool:
        """由 HTTP 回调调用，设置 Future 结果以唤醒等待中的 Scheduler。

        Returns ``True`` if the call_id was found and resolved.
        """
        future = self._pending.get(call_id)
        if future is None:
            logger.warning("resolve_approval: call_id=%s not found (expired?)", call_id)
            return False

        if future.done():
            logger.warning("resolve_approval: call_id=%s already resolved", call_id)
            return False

        future.set_result(outcome)
        logger.info("Approval resolved: call_id=%s, outcome=%s", call_id, outcome)
        return True

    @property
    def pending_count(self) -> int:
        return len(self._pending)
