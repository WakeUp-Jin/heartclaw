"""统一回复模块 — 将 Agent 回复分发到多个渠道。"""

from core.reply.types import ReplyEnvelope
from core.reply.backend import ReplyBackend, FutureBackend, CliBackend, FeishuBackend
from core.reply.dispatcher import ReplyDispatcher

__all__ = [
    "ReplyEnvelope",
    "ReplyBackend",
    "FutureBackend",
    "CliBackend",
    "FeishuBackend",
    "ReplyDispatcher",
]
