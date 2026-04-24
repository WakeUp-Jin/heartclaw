"""消息队列类型定义。"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Literal


class MessagePriority(IntEnum):
    INTERRUPT = 0
    USER = 1
    CRON = 2
    TICK = 3


MessageMode = Literal["user", "cron", "tick"]


@dataclass
class QueueMessage:
    """队列中的消息单元。

    ``_future`` 由 ``MessageQueue.enqueue()`` 自动设置，
    调用者通过 ``await future`` 等待处理结果。
    """

    priority: int
    mode: MessageMode
    content: str
    chat_id: str = ""
    open_id: str = ""
    source_channel: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    created_at: float = field(default_factory=time.time)
    _future: asyncio.Future[str] | None = field(
        default=None, repr=False, compare=False,
    )

    def __lt__(self, other: QueueMessage) -> bool:
        """PriorityQueue 需要元素可比较；优先级相同时按创建时间排序。"""
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at
