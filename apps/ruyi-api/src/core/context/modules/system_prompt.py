"""Segmented system prompt context.

The system prompt is composed of ordered segments, each with an id, priority,
and enable flag.  Core segments are defined by the system; dynamic segments
can be registered by external modules (e.g. user-defined prompts loaded from
files, tool descriptions, memory injection, etc.).

Segments are assembled in **descending** priority order (higher priority
appears earlier in the final prompt) and returned as a single ``SystemPart``
inside ``ContextParts``.
"""

from __future__ import annotations

from core.context.base import BaseContext
from core.context.types import PromptSegment, ContextParts, SystemPart
from core.prompts.system import DEFAULT_SYSTEM_PROMPT

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
        # [表达式 for 变量 in 可迭代对象 if 条件]
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

    def format(self) -> ContextParts:
        prompt = self.get_prompt()
        if not prompt:
            return ContextParts()
        return ContextParts(system_parts=[
            SystemPart(tag="system_prompt", description="", content=prompt),
        ])
