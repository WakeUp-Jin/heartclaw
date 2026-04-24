"""回复后端 — Protocol 定义 + 内置实现。

每个 Backend 决定自己是否处理某条回复（通过检查 envelope 的字段），
ReplyDispatcher 会将每条回复广播给所有已注册的 Backend。
"""

from __future__ import annotations

from typing import Protocol, TYPE_CHECKING

from core.reply.types import ReplyEnvelope
from utils.logger import get_logger

if TYPE_CHECKING:
    from channels.feishu.channel import FeishuChannel

logger = get_logger("reply_backend")


class ReplyBackend(Protocol):
    """回复后端协议 — 所有 Backend 必须实现此接口。"""

    name: str

    async def send(self, envelope: ReplyEnvelope) -> None: ...


class FutureBackend:
    """将回复写入 Future，供 API 路由 / 飞书 on_message 的 await 拿到结果。

    只在 envelope 携带 _future 时才生效；
    cron / tick 等没有 future 的消息会被跳过。
    """

    name = "future"

    async def send(self, envelope: ReplyEnvelope) -> None:
        if envelope._future and not envelope._future.done():
            envelope._future.set_result(envelope.text)


class CliBackend:
    """终端输出回复（观察 / 调试用）。

    始终输出，方便在 docker logs 或终端里观察 Agent 回复。
    """

    name = "cli"

    async def send(self, envelope: ReplyEnvelope) -> None:
        logger.info("[%s] Agent > %s", envelope.mode, envelope.text[:200])


class FeishuBackend:
    """通过飞书 API 发送回复消息。

    发送条件（全部满足才发送）：
    - envelope 有 chat_id（知道发给谁）
    - envelope 有 text（有内容可发）
    - source_channel 是 "feishu" 或空值（cron/tick 等无渠道来源的消息）
      — source_channel="api" 的消息只走 HTTP 返回，不发飞书
    """

    name = "feishu"

    def __init__(self, channel: FeishuChannel) -> None:
        self._channel = channel

    async def send(self, envelope: ReplyEnvelope) -> None:
        if not envelope.chat_id or not envelope.text:
            return
        if envelope.source_channel not in ("feishu", ""):
            return
        try:
            await self._channel.send_message(envelope.chat_id, envelope.text)
        except Exception:
            logger.error(
                "FeishuBackend failed to send to chat_id=%s",
                envelope.chat_id, exc_info=True,
            )
