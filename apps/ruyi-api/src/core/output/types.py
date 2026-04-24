"""统一输出系统 — 事件类型定义。

所有输出事件继承自 OutputEvent 基类，
由 OutputEmitter 分发到已注册的各个后端。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


@dataclass
class OutputEvent:
    """所有输出事件的基类。"""

    source: str  # "ruyi" | "kairos" | "cron"
    timestamp: str = field(default_factory=_now)


@dataclass
class ToolExecutingEvent(OutputEvent):
    """工具开始执行。

    content 携带 LLM 在本轮工具调用前返回的伴随文本（如"让我搜索一下"）。
    同一批 tool_calls 中只有第一个工具携带 content，后续为空。
    """

    call_id: str = ""
    tool_name: str = ""
    args_summary: str = ""
    content: str = ""


@dataclass
class ToolDoneEvent(OutputEvent):
    """工具执行完成（成功 / 失败 / 取消）。"""

    call_id: str = ""
    tool_name: str = ""
    success: bool = True
    status: str = "success"  # "success" | "error" | "cancelled"
    result_preview: str = ""
    error: str | None = None
    duration_ms: float = 0


@dataclass
class FinalReplyEvent(OutputEvent):
    """Agent / Kairos / Cron 的最终回复文本（替代原 ReplyEnvelope）。"""

    text: str = ""
    mode: str = ""  # "user" | "cron" | "tick"
    chat_id: str = ""
    open_id: str = ""
    source_channel: str = ""  # "feishu" | "api" | ""
    source_msg_id: str = ""
    _future: asyncio.Future[str] | None = field(
        default=None, repr=False, compare=False,
    )


@dataclass
class KairosLifecycleEvent(OutputEvent):
    """Kairos 自治模式的生命周期事件。"""

    event: str = ""  # "tick_start" | "tick_done" | "sleep_start" | "sleep_interrupted" | "sleep_done" | "cron_fired"
    detail: dict = field(default_factory=dict)
