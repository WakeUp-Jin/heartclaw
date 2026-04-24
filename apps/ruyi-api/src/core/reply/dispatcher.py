"""ReplyDispatcher — 将回复广播到所有已注册的 Backend。"""

from __future__ import annotations

from core.reply.backend import ReplyBackend
from core.reply.types import ReplyEnvelope
from utils.logger import get_logger

logger = get_logger("reply_dispatcher")


class ReplyDispatcher:
    """将一条 ReplyEnvelope 依次发送给所有已注册的 Backend。

    单个 Backend 失败不影响其他 Backend 的执行。
    """

    def __init__(self) -> None:
        self._backends: list[ReplyBackend] = []

    def add_backend(self, backend: ReplyBackend) -> None:
        self._backends.append(backend)
        logger.info("Reply backend registered: %s", backend.name)

    async def dispatch(self, envelope: ReplyEnvelope) -> None:
        for backend in self._backends:
            try:
                await backend.send(envelope)
            except Exception:
                logger.error(
                    "Reply backend '%s' failed for msg=%s",
                    backend.name, envelope.source_msg_id, exc_info=True,
                )
