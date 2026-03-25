"""Short-term memory context module.

Manages the continuous memory stream and compression.  There is no
"conversation" boundary — memory is a rolling flow of ContextItems
persisted as time-stamped segments.

Persistence: ``ShortMemoryStore`` (time-folder + JSONL).
Compression: ``ContextCompressor`` (LLM-based summarisation).
"""

from __future__ import annotations

from typing import Callable, Awaitable

from core.context.base import BaseContext
from core.context.types import ContextItem, CompressionResult, MessagePriority
from core.context.utils.compressor import ContextCompressor
from core.context.utils.token_estimator import TokenEstimator
from utils import logger


class ShortTermMemoryContext(BaseContext[ContextItem]):
    """Continuous memory stream with LLM-based compression."""

    def __init__(
        self,
        storage,
        compressor: ContextCompressor | None = None,
        token_estimator: TokenEstimator | None = None,
    ) -> None:
        super().__init__()
        self._storage = storage
        self._compressor = compressor or ContextCompressor()
        self._estimator = token_estimator or TokenEstimator()
        self._summary: str = ""

        self._load_memory()

    # ------------------------------------------------------------------
    # Message operations
    # ------------------------------------------------------------------

    def append_message(self, item: ContextItem) -> None:
        """Append to both in-memory list and persistent storage."""
        self.add(item)
        self._storage.append(item.to_dict())

    # ------------------------------------------------------------------
    # Compression
    # ------------------------------------------------------------------

    def needs_compression(self, max_tokens: int, threshold: float = 0.8) -> bool:
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
        """Compress the older portion of memory via LLM summary.

        Flow:
        1. Prepend existing summary (if any) to the item list
        2. LLM summarises the oldest 70%, keeps newest 30%
        3. Write checkpoint.json to the current segment
        4. Rotate to a new segment folder for future appends
        5. Update in-memory state
        """
        if not self._items:
            return CompressionResult(compressed=False, reason="empty")

        items_with_context = list(self._items)
        if self._summary:
            items_with_context.insert(0, ContextItem(
                role="system",
                content=f"之前的摘要：\n{self._summary}",
                source="summary",
                priority=MessagePriority.HIGH,
            ))

        result = await self._compressor.compress_with_llm(
            items_with_context, keep_ratio, summarize_fn,
        )

        if not result.compressed:
            return result

        checkpoint_line = self._storage.count_lines() - result.kept_count
        self._storage.save_checkpoint(result.summary, checkpoint_line)

        self._summary = result.summary
        kept_items = self._items[-result.kept_count:] if result.kept_count > 0 else []
        self._items = kept_items

        if hasattr(self._storage, "rotate"):
            new_dir = self._storage.rotate()
            for item in kept_items:
                self._storage.append(item.to_dict())
            logger.info("Rotated memory segment -> %s", new_dir.name)

        logger.info(
            "ShortTermMemory compressed: %d removed, %d kept, checkpoint at line %d",
            result.removed_count, result.kept_count, checkpoint_line,
        )
        return result

    # ------------------------------------------------------------------
    # Clear (archive current segment, start fresh)
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Archive current memory and start a fresh segment."""
        super().clear()
        self._summary = ""
        if hasattr(self._storage, "rotate"):
            self._storage.rotate()
        logger.info("Short-term memory cleared, new segment started")

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
    # Internal: load memory from storage
    # ------------------------------------------------------------------

    def _load_memory(self) -> None:
        """Load the active segment from storage.

        If a checkpoint exists, loads summary + items after the checkpoint line.
        Otherwise loads everything.  Uses ``ContextItem.from_dict`` so all
        persisted metadata (thinking, usage, etc.) is restored.
        """
        checkpoint = self._storage.load_checkpoint()

        if checkpoint:
            self._summary = checkpoint.get("summary", "")
            kept_from = checkpoint.get("kept_from_line", checkpoint.get("checkpoint_line", 0))
            raw = self._storage.load_from_line(kept_from)
            self._items = [ContextItem.from_dict(d) for d in raw]
            logger.info(
                "Loaded memory with checkpoint: summary=%d chars, %d items from line %d",
                len(self._summary), len(self._items), kept_from,
            )
        else:
            self._summary = ""
            raw = self._storage.load_all()
            self._items = [ContextItem.from_dict(d) for d in raw]
            logger.info("Loaded memory: %d items (no checkpoint)", len(self._items))
