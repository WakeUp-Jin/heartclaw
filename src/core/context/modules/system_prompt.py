"""Segmented system prompt context.

The system prompt is composed of ordered segments, each with an id, priority,
and enable flag.  Core segments are defined by the system; dynamic segments
can be registered by external modules (e.g. user-defined prompts loaded from
files, tool descriptions, memory injection, etc.).

Segments are assembled in **descending** priority order (higher priority
appears earlier in the final prompt) and merged into a single ``system``
ContextItem.
"""

from __future__ import annotations

from core.context.base import BaseContext
from core.context.types import ContextItem, MessagePriority, PromptSegment

DEFAULT_SYSTEM_PROMPT = """\
你是 PineClaw，一个基于飞书的个人 AI 助手。你可以帮助用户：

- 创建、读取、修改飞书文档
- 创建和操作多维表格（Bitable）
- 浏览飞书云空间文件夹
- 创建和管理飞书任务
- 发送消息

你有一个长期记忆系统。你可以通过以下方式使用它：

1. **读取记忆**：每次对话开始时，你的上下文中会自动包含记忆内容，无需手动读取。

2. **写入记忆**：当对话中出现以下情况时，调用 memory(action="append") 工具记录：
   - 用户提到个人信息（名字、职业、团队等）
   - 用户表达偏好（代码风格、回复语言、工作习惯等）
   - 发生重要事件或决策
   - 不要记录临时性、一次性的信息

3. **整理记忆**：如果记忆内容变得冗长或有重复，调用 memory(action="rewrite") 整理。

4. **基于记忆回复**：始终参考记忆中的用户画像和偏好来个性化你的回复。

请使用中文回复用户。回复应当简洁、有帮助。当你调用工具完成操作后，\
用自然语言告知用户结果。\
"""

CORE_SEGMENT_ID = "core"
CORE_SEGMENT_PRIORITY = 100


class SystemPromptContext(BaseContext[PromptSegment]):
    """Segmented system prompt supporting dynamic registration."""

    def __init__(self, core_prompt: str | None = None) -> None:
        super().__init__()
        self.add(PromptSegment(
            id=CORE_SEGMENT_ID,
            content=core_prompt or DEFAULT_SYSTEM_PROMPT,
            priority=CORE_SEGMENT_PRIORITY,
        ))

    # ------------------------------------------------------------------
    # Segment management
    # ------------------------------------------------------------------

    def register_segment(self, segment: PromptSegment) -> None:
        """Register a new segment.  Replaces existing segment with same id."""
        self._items = [s for s in self._items if s.id != segment.id]
        self.add(segment)

    def update_segment(self, segment_id: str, content: str) -> None:
        for seg in self._items:
            if seg.id == segment_id:
                seg.content = content
                return

    def remove_segment(self, segment_id: str) -> None:
        self._items = [s for s in self._items if s.id != segment_id]

    def enable_segment(self, segment_id: str) -> None:
        for seg in self._items:
            if seg.id == segment_id:
                seg.enabled = True
                return

    def disable_segment(self, segment_id: str) -> None:
        for seg in self._items:
            if seg.id == segment_id:
                seg.enabled = False
                return

    def get_segment(self, segment_id: str) -> PromptSegment | None:
        for seg in self._items:
            if seg.id == segment_id:
                return seg
        return None

    # ------------------------------------------------------------------
    # Prompt assembly
    # ------------------------------------------------------------------

    def get_prompt(self) -> str:
        """Return the full assembled prompt string (enabled segments only)."""
        enabled = [s for s in self._items if s.enabled]
        enabled.sort(key=lambda s: s.priority, reverse=True)
        return "\n\n".join(s.content for s in enabled if s.content.strip())

    # ------------------------------------------------------------------
    # BaseContext interface
    # ------------------------------------------------------------------

    def format(self) -> list[ContextItem]:
        prompt = self.get_prompt()
        if not prompt:
            return []
        return [ContextItem(
            role="system",
            content=prompt,
            source="system_prompt",
            priority=MessagePriority.CRITICAL,
        )]
