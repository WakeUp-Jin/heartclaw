"""回复模块类型定义。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class ReplyEnvelope:
    """一条待发送的回复。

    由 QueueProcessor 在 dispatch 完成后构造，
    交给 ReplyDispatcher 广播到所有已注册的 Backend。

    Parameters
    ----------
    text:
        LLM 回复的文本内容。
    mode:
        消息来源类型 — "user" | "cron" | "tick"。
    chat_id:
        飞书 chat_id，用于定向回复。
    open_id:
        飞书 open_id，标识发送者。
    source_channel:
        消息来源渠道 — "feishu" | "api" | "" 等，
        Backend 用来判断是否需要处理（如 FeishuBackend 只回复来自 feishu 或无渠道的消息）。
    source_msg_id:
        原始 QueueMessage 的 id，用于追踪。
    _future:
        来自 QueueMessage 的 Future，FutureBackend 通过它把结果
        传回给 await 的调用者（API 路由 / 飞书 on_message）。
    """

    text: str
    mode: str
    chat_id: str = ""
    open_id: str = ""
    source_channel: str = ""
    source_msg_id: str = ""
    _future: asyncio.Future[str] | None = field(
        default=None, repr=False, compare=False,
    )
