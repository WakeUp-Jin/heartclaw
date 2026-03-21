"""Short-term memory context module.

Manages the conversation history and compression.  Replaces the previous
mixed responsibility in ``ContextManager`` (``_messages`` + ``_summary``).

Persistence is delegated to an ``IContextStorage`` implementation; compression
is delegated to ``ContextCompressor``.
"""

from __future__ import annotations

from typing import Any, Callable, Awaitable

from core.context.base import BaseContext
from core.context.types import ContextItem, CompressionResult, MessagePriority
from core.context.storage.base import IContextStorage
from core.context.utils.compressor import ContextCompressor
from core.context.utils.token_estimator import TokenEstimator
from utils import logger


class ShortTermMemoryContext(BaseContext[ContextItem]):
    """Conversation history with LLM-based compression."""

    def __init__(
        self,
        storage: IContextStorage,
        compressor: ContextCompressor | None = None,
        token_estimator: TokenEstimator | None = None,
    ) -> None:
        super().__init__()
        self._storage = storage
        self._compressor = compressor or ContextCompressor()
        self._estimator = token_estimator or TokenEstimator()
        self._summary: str = ""

        self._load_session()

    # ------------------------------------------------------------------
    # Message operations
    # ------------------------------------------------------------------

    def append_message(self, item: ContextItem) -> None:
        """Append to both in-memory list and persistent storage."""
        self.add(item)
        self._storage.append(item.to_message())

    # ------------------------------------------------------------------
    # Compression
    # ------------------------------------------------------------------

    def needs_compression(self, max_tokens: int, threshold: float = 0.7) -> bool:
        tokens = self.estimate_tokens()
        return tokens >= int(max_tokens * threshold)

    def estimate_tokens(self) -> int:
        total = self._estimator.estimate_items(self._items)
        if self._summary:
            total += TokenEstimator.estimate_text(self._summary)
        return total

    async def compress(
        self,
        summarize_fn: Callable[[str], Awaitable[str]],
        keep_ratio: float = 0.3,
    ) -> CompressionResult:
        """Run LLM-based compression on the history."""
        if not self._items:
            return CompressionResult(compressed=False, reason="empty")

        # Prepend existing summary to the items to compress
        items_with_context = list(self._items)
        if self._summary:
            items_with_context.insert(0, ContextItem(
                role="system",
                content=f"之前的摘要：\n{self._summary}",
                source="summary",
                priority=MessagePriority.HIGH,
            ))

        result = await self._compressor.compress_with_llm(
            items_with_context, keep_ratio, summarize_fn
        )

        if not result.compressed:
            return result

        # Persist checkpoint
        checkpoint_line = self._storage.count_lines() - result.kept_count
        self._storage.save_checkpoint(result.summary, checkpoint_line)

        # Update in-memory state: keep only recent items
        self._summary = result.summary
        self._items = self._items[-result.kept_count:] if result.kept_count > 0 else []

        logger.info(
            "ShortTermMemory compressed: %d removed, %d kept, checkpoint at line %d",
            result.removed_count, result.kept_count, checkpoint_line,
        )
        return result

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Start a new conversation session."""
        super().clear()
        self._summary = ""
        self._storage.new_session()
        logger.info("Short-term memory cleared, new session started")

    # ------------------------------------------------------------------
    # BaseContext interface
    # ------------------------------------------------------------------

    def format(self) -> list[ContextItem]:
        result: list[ContextItem] = []

        if self._summary:
            result.append(ContextItem(
                role="system",
                content=f"以下是之前对话的压缩摘要：\n\n{self._summary}",
                source="summary",
                priority=MessagePriority.HIGH,
            ))

        result.extend(self._items)
        return result

    # ------------------------------------------------------------------
    # Internal: session loading
    # ------------------------------------------------------------------

    def _load_session(self) -> None:
        checkpoint = self._storage.load_checkpoint()

        if checkpoint:
            self._summary = checkpoint.get("summary", "")
            checkpoint_line = checkpoint.get("checkpoint_line", 0)
            raw_messages = self._storage.load_from_line(checkpoint_line)
            self._items = [
                ContextItem.from_message(m, source="history")
                for m in raw_messages
            ]
            logger.info(
                "Loaded session with checkpoint: summary=%d chars, %d messages from line %d",
                len(self._summary), len(self._items), checkpoint_line,
            )
        else:
            self._summary = ""
            raw_messages = self._storage.load_all()
            self._items = [
                ContextItem.from_message(m, source="history")
                for m in raw_messages
            ]
            logger.info("Loaded session: %d messages (no checkpoint)", len(self._items))
