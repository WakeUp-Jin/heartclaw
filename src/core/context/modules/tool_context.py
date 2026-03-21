"""Tool context module — manages the current tool-call sequence.

Tracks the pairing between assistant ``tool_calls`` messages and their
corresponding ``tool`` response messages.  Provides sanitisation to
clean up incomplete chains (e.g. when the user cancels mid-execution).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.context.base import BaseContext
from core.context.types import ContextItem, MessagePriority
from core.context.utils.message_sanitizer import sanitize_messages

if TYPE_CHECKING:
    from core.context.modules.short_term_memory import ShortTermMemoryContext


class ToolContext(BaseContext[ContextItem]):
    """Manages the tool-call chain for the current turn."""

    def add_tool_call(self, assistant_item: ContextItem) -> None:
        """Append an assistant message that contains ``tool_calls``."""
        self.add(assistant_item)

    def add_tool_response(self, tool_item: ContextItem) -> None:
        """Append a tool response message."""
        self.add(tool_item)

    def has_pending_calls(self) -> bool:
        """Return ``True`` if there are tool_calls without matching responses."""
        call_ids: set[str] = set()
        response_ids: set[str] = set()

        for item in self._items:
            if item.role == "assistant" and item.tool_calls:
                for tc in item.tool_calls:
                    tc_id = tc.get("id")
                    if tc_id:
                        call_ids.add(tc_id)
            elif item.role == "tool" and item.tool_call_id:
                response_ids.add(item.tool_call_id)

        return bool(call_ids - response_ids)

    def sanitize(self) -> None:
        """Remove incomplete tool-call chains from the current turn."""
        messages = [item.to_message() for item in self._items]
        cleaned = sanitize_messages(messages)

        # Rebuild items from cleaned messages, preserving metadata from originals
        cleaned_set = {id(m) for m in cleaned}
        original_messages = [item.to_message() for item in self._items]

        keep_indices: list[int] = []
        for i, orig_msg in enumerate(original_messages):
            for clean_msg in cleaned:
                if orig_msg is clean_msg:
                    keep_indices.append(i)
                    break

        # Fallback: match by content comparison if reference matching fails
        if len(keep_indices) != len(cleaned):
            keep_indices = []
            used: set[int] = set()
            for clean_msg in cleaned:
                for i, item in enumerate(self._items):
                    if i not in used and item.to_message() == clean_msg:
                        keep_indices.append(i)
                        used.add(i)
                        break

        self._items = [self._items[i] for i in sorted(keep_indices)]

    def archive_to(self, short_term: ShortTermMemoryContext) -> None:
        """Move all items from this turn into short-term memory, then clear."""
        for item in self._items:
            short_term.append_message(item)
        self.clear()

    # ------------------------------------------------------------------
    # BaseContext interface
    # ------------------------------------------------------------------

    def format(self) -> list[ContextItem]:
        return list(self._items)
