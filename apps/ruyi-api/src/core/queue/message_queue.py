"""优先级消息队列。

所有消息源（用户输入、定时任务触发、KAIROS tick）统一入队，
由 QueueProcessor 按优先级串行消费。
"""

from __future__ import annotations

import asyncio

from core.queue.types import QueueMessage
from utils.logger import get_logger

logger = get_logger("message_queue")


class MessageQueue:
    """线程安全的 asyncio 优先级消息队列。"""

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[QueueMessage] = asyncio.PriorityQueue()
        self._wake_event = asyncio.Event()

    async def enqueue(self, msg: QueueMessage) -> asyncio.Future[str]:
        """入队并返回 Future，调用者可 await 获取执行结果。"""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        msg._future = future
        await self._queue.put(msg)
        self._wake_event.set()
        logger.debug(
            "Enqueued [%s] priority=%d id=%s",
            msg.mode, msg.priority, msg.id,
        )
        return future

    async def dequeue(self) -> QueueMessage:
        """取出优先级最高（数值最小）的消息，队列为空时阻塞。"""
        return await self._queue.get()

    def has_pending(self) -> bool:
        return not self._queue.empty()

    @property
    def wake_event(self) -> asyncio.Event:
        return self._wake_event
