"""Token estimation without external tokenizer dependencies.

Uses character-based heuristics: CJK characters map ~1.5 chars per token,
ASCII text maps ~4 chars per token.  Adds per-message overhead for role metadata.
"""

from __future__ import annotations

import json
from typing import Any

from core.context.types import ContextItem


class TokenEstimator:
    """Estimate token counts for text, ContextItems, and message dicts."""

    # per-message overhead: role tag + separators
    _MESSAGE_OVERHEAD = 4

    @staticmethod
    def estimate_text(text: str) -> int:
        """Estimate tokens for a plain string."""
        if not text:
            return 0
        tokens = 0.0
        for ch in text:
            if "\u4e00" <= ch <= "\u9fff":
                tokens += 1 / 1.5
            else:
                tokens += 1 / 4
        return max(1, int(tokens + 0.5))

    def estimate_item(self, item: ContextItem) -> int:
        """Estimate tokens for a single ContextItem."""
        total = self._MESSAGE_OVERHEAD
        if item.content:
            total += self.estimate_text(item.content)
        if item.tool_calls:
            total += self.estimate_text(json.dumps(item.tool_calls, ensure_ascii=False))
        if item.tool_call_id:
            total += self.estimate_text(item.tool_call_id)
        if item.name:
            total += self.estimate_text(item.name)
        return total

    def estimate_items(self, items: list[ContextItem]) -> int:
        return sum(self.estimate_item(it) for it in items)

    def estimate_message(self, message: dict[str, Any]) -> int:
        """Estimate tokens for a single message dict."""
        total = self._MESSAGE_OVERHEAD
        content = message.get("content")
        if content:
            total += self.estimate_text(content)
        for tc in message.get("tool_calls", []):
            fn = tc.get("function", {})
            total += self.estimate_text(fn.get("arguments", ""))
            total += self.estimate_text(fn.get("name", ""))
        tool_call_id = message.get("tool_call_id")
        if tool_call_id:
            total += self.estimate_text(tool_call_id)
        name = message.get("name")
        if name:
            total += self.estimate_text(name)
        return total

    def estimate_messages(self, messages: list[dict[str, Any]]) -> int:
        return sum(self.estimate_message(m) for m in messages)

    @staticmethod
    def format_tokens(tokens: int) -> str:
        if tokens >= 1_000_000:
            return f"{tokens / 1_000_000:.1f}M"
        if tokens >= 1_000:
            return f"{tokens / 1_000:.1f}K"
        return str(tokens)
