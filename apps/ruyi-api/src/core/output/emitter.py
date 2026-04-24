"""OutputEmitter — 统一输出分发器。

所有输出（工具状态、最终回复、Kairos 事件）通过 emitter.emit(event)
一个入口进入，由注册的后端各自决定如何处理。
"""

from __future__ import annotations

from typing import Protocol

from core.output.types import OutputEvent
from utils.logger import get_logger

logger = get_logger("output.emitter")


class OutputBackend(Protocol):
    """输出后端协议 — 所有后端必须实现此接口。"""

    name: str

    async def handle(self, event: OutputEvent) -> None: ...


class OutputEmitter:
    """统一输出分发器，替代原来的 ReplyDispatcher。

    所有输出事件通过 emit() 一个入口进入，
    由注册的后端各自决定是否处理、如何处理。
    单个后端异常不影响其他后端的执行。
    """

    def __init__(self) -> None:
        self._backends: list[OutputBackend] = []

    def add_backend(self, backend: OutputBackend) -> None:
        self._backends.append(backend)
        logger.info("Output backend registered: %s", backend.name)

    async def emit(self, event: OutputEvent) -> None:
        for backend in self._backends:
            try:
                await backend.handle(event)
            except Exception:
                logger.error(
                    "Output backend '%s' failed for %s",
                    backend.name,
                    type(event).__name__,
                    exc_info=True,
                )
