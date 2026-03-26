"""Short-term memory context module.

Manages the continuous memory stream and compression.  All message
types (user input, tool calls, tool responses, assistant replies) are
stored here as a unified rolling flow of ContextItems, persisted as
time-stamped JSONL segments.

On load, incomplete tool-call chains (caused by a mid-execution crash)
are automatically sanitised so the message sequence stays valid for
the LLM API.

Persistence: ``ShortMemoryStore`` (time-folder + JSONL).
Compression: ``ContextCompressor`` (LLM-based summarisation).
"""

from __future__ import annotations

from typing import Callable, Awaitable

from core.context.base import BaseContext
from core.context.types import ContextItem, CompressionResult, MessagePriority
from core.context.utils.compressor import ContextCompressor
from core.context.utils.message_sanitizer import sanitize_messages
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
        self._turn_start: int = 0

        self._load_memory()

    # ------------------------------------------------------------------
    # Message operations
    # ------------------------------------------------------------------

    def append_message(self, item: ContextItem) -> None:
        """Append to both in-memory list and persistent storage."""
        self.add(item)
        self._storage.append(item.to_dict())

    # ------------------------------------------------------------------
    # Turn tracking
    # ------------------------------------------------------------------

    def mark_turn_start(self) -> None:
        """Record where the current turn begins in the items list.

        Called by Agent before starting each engine run so that
        compression knows which messages belong to the in-progress turn
        and should not be compressed away.
        """
        self._turn_start = len(self._items)

    def get_current_turn_items(self) -> list[ContextItem]:
        """Return items added since the last ``mark_turn_start()``."""
        return list(self._items[self._turn_start:])

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

        Only items *before* ``_turn_start`` are eligible for compression.
        Items from the current turn are always kept intact so that an
        in-progress tool chain is never summarised away.

        Flow:
        1. Separate items into compressible (before turn) and protected (current turn)
        2. Prepend existing summary (if any) to the compressible list
        3. LLM summarises the oldest portion, keeps newest portion
        4. Write checkpoint.json to the current segment
        5. Rotate to a new segment folder for future appends
        6. Rebuild in-memory state: kept items + current-turn items
        """
        compressible = self._items[:self._turn_start]
        current_turn = self._items[self._turn_start:]

        if not compressible:
            return CompressionResult(compressed=False, reason="empty")

        items_with_context = list(compressible)
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

        kept_from_compressible = compressible[-result.kept_count:] if result.kept_count > 0 else []

        checkpoint_line = self._storage.count_lines() - result.kept_count - len(current_turn)
        self._storage.save_checkpoint(result.summary, checkpoint_line)

        self._summary = result.summary
        self._items = kept_from_compressible + current_turn
        self._turn_start = len(kept_from_compressible)

        if hasattr(self._storage, "rotate"):
            new_dir = self._storage.rotate()
            for item in self._items:
                self._storage.append(item.to_dict())
            logger.info("Rotated memory segment -> %s", new_dir.name)

        logger.info(
            "ShortTermMemory compressed: %d removed, %d kept (+ %d current-turn protected)",
            result.removed_count, result.kept_count, len(current_turn),
        )
        return result

    # ------------------------------------------------------------------
    # Clear (archive current segment, start fresh)
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Archive current memory and start a fresh segment."""
        super().clear()
        self._summary = ""
        self._turn_start = 0
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

        After loading, ``_sanitize_on_load`` removes any incomplete
        tool-call chains that may have been left by a previous crash.
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

        self._sanitize_on_load()
        self._turn_start = len(self._items)

    def _sanitize_on_load(self) -> None:
        """Remove incomplete tool-call chains left by a previous crash.

        Converts items to message dicts, runs ``sanitize_messages`` to
        strip unpaired tool_calls / tool responses, then rebuilds the
        items list keeping only the messages that survived sanitisation.
        """
        if not self._items:
            return

        messages = [item.to_message() for item in self._items]
        cleaned = sanitize_messages(messages)

        if len(cleaned) == len(messages):
            return

        cleaned_set: set[int] = set()
        used: set[int] = set()
        for clean_msg in cleaned:
            for i, item in enumerate(self._items):
                if i not in used and item.to_message() == clean_msg:
                    cleaned_set.add(i)
                    used.add(i)
                    break

        removed = len(self._items) - len(cleaned_set)
        self._items = [self._items[i] for i in sorted(cleaned_set)]
        logger.warning(
            "Sanitized %d incomplete tool message(s) on load", removed,
        )
