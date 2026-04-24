"""Agent 协程级上下文变量。

使用 Python contextvars，在同一个 asyncio 协程调用链中共享数据，
不同协程之间互不干扰。
"""

from contextvars import ContextVar

current_chat_id: ContextVar[str] = ContextVar("current_chat_id", default="")
