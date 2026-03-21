"""Long-term memory context module.

Bridges the existing ``MemoryStore`` (Feishu-backed persistent storage) into
the context pipeline.  This module is read-only at the context level —
writes go through the ``MemoryStore`` / memory tools directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.context.base import BaseContext
from core.context.types import ContextItem, MessagePriority

if TYPE_CHECKING:
    from memory.memory_store import MemoryStore

MEMORY_PREAMBLE = "以下是你对用户的长期记忆，请基于这些信息个性化回复：\n\n"


class LongTermMemoryContext(BaseContext[str]):
    """Injects long-term memory text into the LLM context."""

    def __init__(self, memory_store: MemoryStore) -> None:
        super().__init__()
        self._store = memory_store

    def refresh(self) -> None:
        """Reload memory text from the backing store into the item list."""
        self.clear()
        text = self._store.get_memory_text()
        if text and text.strip():
            self.add(text)

    def format(self) -> list[ContextItem]:
        all_text = self.get_all()
        if not all_text:
            text = self._store.get_memory_text()
            if not text or not text.strip():
                return []
        else:
            text = "\n".join(all_text)

        return [ContextItem(
            role="system",
            content=f"{MEMORY_PREAMBLE}{text}",
            source="long_term_memory",
            priority=MessagePriority.HIGH,
        )]
