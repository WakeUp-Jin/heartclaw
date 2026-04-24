"""Long-term memory context module.

Only loads ``user_instructions.md`` into the system prompt.  The other
three files (user_profile, facts_and_decisions, topics_and_interests) are
part of the Skill's progressive disclosure Layer 3 -- the Agent reads
them on demand via the ReadFile tool based on the SKILL.md index.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.context.base import BaseContext
from core.context.types import ContextParts, SystemPart

if TYPE_CHECKING:
    from storage.memory_store import LocalMemoryStore


class LongTermMemoryContext(BaseContext[str]):
    """Injects user_instructions.md into the LLM system prompt."""

    def __init__(self, memory_store: LocalMemoryStore) -> None:
        super().__init__()
        self._store = memory_store

    def format(self) -> ContextParts:
        text = self._store.read_file("user_instructions")
        if not text or not text.strip():
            return ContextParts()

        return ContextParts(system_parts=[
            SystemPart(
                tag="user_instructions",
                description="用户对你的明确指令和规则，必须严格遵守",
                content=text,
            ),
        ])
