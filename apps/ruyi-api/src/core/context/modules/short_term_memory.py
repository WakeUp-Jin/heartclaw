"""Short-term memory context module.

Manages the continuous memory stream with token-budgeted loading and
multi-layer compression (week / month / year summaries).

All message types (user input, tool calls, tool responses, assistant replies)
are stored as daily .jsonl files.  On load, content is loaded from newest
to oldest within a token budget.  When the budget overflows, the oldest
daily records are compressed into summary files.

Persistence: ``ShortMemoryStore`` (daily .jsonl + monthly folders).
Compression: ``ContextCompressor`` (LLM-based multi-layer summarisation).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Awaitable

from core.context.base import BaseContext
from core.context.types import (
    ContextItem, CompressionResult, MessagePriority,
    ContextParts, SystemPart,
)
from core.context.utils.compressor import ContextCompressor
from core.context.utils.message_sanitizer import sanitize_messages
from core.context.utils.token_estimator import TokenEstimator
from storage.short_memory_store import ShortMemoryStore
from utils.logger import logger


class ShortTermMemoryContext(BaseContext[ContextItem]):
    """Continuous memory stream with token-budgeted loading and multi-layer compression."""

    def __init__(
        self,
        storage: ShortMemoryStore,
        compressor: ContextCompressor | None = None,
        token_estimator: TokenEstimator | None = None,
        context_window: int = 128_000,
        initial_load_ratio: float = 0.60,
    ) -> None:
        super().__init__()
        self._storage = storage
        self._compressor = compressor or ContextCompressor()
        self._estimator = token_estimator or TokenEstimator()
        self._context_window = context_window
        self._initial_load_ratio = initial_load_ratio

        self._loaded_summaries: list[tuple[str, str]] = []
        self._intra_day_summary: str = ""
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
        self._turn_start = len(self._items)

    def get_current_turn_items(self) -> list[ContextItem]:
        return list(self._items[self._turn_start:])

    # ------------------------------------------------------------------
    # Compression
    # ------------------------------------------------------------------

    def needs_compression(self, max_tokens: int, threshold: float = 0.85) -> bool:
        tokens = self.estimate_tokens()
        return tokens >= int(max_tokens * threshold)

    def estimate_tokens(self) -> int:
        total = self._estimator.estimate_items(self._items)
        for _, text in self._loaded_summaries:
            total += TokenEstimator.estimate_text(text)
        if self._intra_day_summary:
            total += TokenEstimator.estimate_text(self._intra_day_summary)
        return total

    async def compress(
        self,
        summarize_fn: Callable[[str], Awaitable[str]],
        keep_ratio: float = 0.3,
    ) -> CompressionResult:
        """Compress the oldest content to free up token budget.

        Strategy (in order):
        1. If there are daily .jsonl files older than yesterday that aren't
           covered by summaries, compress the oldest batch into a week summary.
        2. If no such files exist but we're still over budget, fall back to
           in-memory compression of the oldest items (within-day overflow).
        """
        result = await self._try_disk_compression(summarize_fn)
        if result.compressed:
            return result

        return await self._try_intra_day_compression(summarize_fn, keep_ratio)

    # ------------------------------------------------------------------
    # Clear
    # ------------------------------------------------------------------

    def clear(self) -> None:
        super().clear()
        self._loaded_summaries.clear()
        self._intra_day_summary = ""
        self._turn_start = 0
        self._storage.rotate_daily()
        logger.info("Short-term memory cleared, new segment created")

    # ------------------------------------------------------------------
    # BaseContext interface
    # ------------------------------------------------------------------

    def format(self) -> ContextParts:
        parts = ContextParts()

        for label, text in self._loaded_summaries:
            parts.system_parts.append(SystemPart(
                tag="memory_summary",
                description=f"历史对话摘要 ({label})",
                content=text,
            ))

        if self._intra_day_summary:
            parts.system_parts.append(SystemPart(
                tag="conversation_summary",
                description="当天早些时候的对话摘要",
                content=self._intra_day_summary,
            ))

        parts.message_items.extend(self._items)
        return parts

    # ------------------------------------------------------------------
    # Internal: load memory from storage with token budget
    # ------------------------------------------------------------------

    def _load_memory(self) -> None:
        """Load from disk based on token budget, newest to oldest.

        加载策略（按优先级从高到低）：
        1. 首先尝试加载日期的摘要（周摘要/月摘要），避免重复加载原始数据
        2. 如果没有摘要覆盖，则加载该日期的原始 .jsonl 文件
        3. 最后加载年摘要（独立的年度总结文件）

        注意：加载顺序是从新到旧，但最终会反转成从早到晚的顺序存入内存，
        保证对话历史的时序正确性。
        
        """
        # 清空现有内存
        self._items.clear()
        self._loaded_summaries.clear()
        self._intra_day_summary = ""

        # 计算 token 预算（根据上下文窗口和初始加载比例）
        budget = int(self._context_window * self._initial_load_ratio)
        used = 0

        # 获取所有存在记忆文件的日期（从新到旧）
        all_dates = self._storage.get_all_dates_descending()
        if not all_dates:
            logger.info("No short-term memory files found")
            self._turn_start = 0
            return

        # 暂存要加载的数据，避免中途修改 self._items
        to_load_items: list[tuple[str, list[ContextItem]]] = []      # (日期标签, 原始消息列表)
        to_load_summaries: list[tuple[str, str]] = []                # (摘要标签, 摘要文本)
        loaded_summary_names: set[str] = set()                       # 已加载的摘要文件名（去重）

        # ------------------------------------------------------------------
        # 第一阶段：遍历所有日期，加载摘要或原始数据
        # ------------------------------------------------------------------
        for d in all_dates:
            if used >= budget:
                break

            # 检查该日期是否被某个摘要文件覆盖
            month_dir = self._storage.get_month_dir(d)
            summaries = self._storage.list_summaries(month_dir)
            covering = self._storage.find_covering_summary(d, summaries)

            if covering and covering.name not in loaded_summary_names:
                # 情况1：有摘要覆盖且未加载过，加载该摘要
                text = self._storage.read_summary(covering)
                if text:
                    tokens = TokenEstimator.estimate_text(text)
                    if used + tokens <= budget:
                        label = covering.name.replace(".summary.md", "")
                        to_load_summaries.append((label, text))
                        loaded_summary_names.add(covering.name)
                        used += tokens
                continue
            elif covering:
                # 情况2：有摘要覆盖但已加载过，跳过该日期
                continue

            # 情况3：无摘要覆盖，加载该日期的原始数据
            raw = self._storage.load_daily(d)
            if not raw:
                continue
            ci = [ContextItem.from_dict(item) for item in raw]
            tokens = self._estimator.estimate_items(ci)

            if used + tokens <= budget:
                to_load_items.append((d.isoformat(), ci))
                used += tokens
            else:
                break

        # ------------------------------------------------------------------
        # 第二阶段：加载年摘要（独立于日期的年度总结）
        # ------------------------------------------------------------------
        for ys in self._storage.list_year_summaries():
            if used >= budget:
                break
            text = self._storage.read_summary(ys)
            if text:
                tokens = TokenEstimator.estimate_text(text)
                if used + tokens <= budget:
                    label = ys.name.replace(".summary.md", "")
                    to_load_summaries.append((label, text))
                    used += tokens

        # ------------------------------------------------------------------
        # 第三阶段：按时间顺序合并数据（从早到晚）
        # ------------------------------------------------------------------
        # 由于遍历是从新到旧，需要反转成从早到晚的时序
        to_load_items.reverse()
        to_load_summaries.reverse()

        # 将暂存的数据写入实际内存
        for _, items in to_load_items:
            self._items.extend(items)
        self._loaded_summaries = to_load_summaries

        # 清理不完整的消息（如工具调用缺少响应等）
        self._sanitize_on_load()
        # 标记当前轮次的起始位置（之前的都是历史）
        self._turn_start = len(self._items)

        logger.info(
            "Loaded short-term memory: %d items from %d day(s), %d summaries, ~%d tokens",
            len(self._items), len(to_load_items), len(self._loaded_summaries), used,
        )

    # ------------------------------------------------------------------
    # Compression: disk-based (daily -> week summary)
    # ------------------------------------------------------------------

    async def _try_disk_compression(
        self,
        summarize_fn: Callable[[str], Awaitable[str]],
    ) -> CompressionResult:
        today = date.today()
        yesterday = today - timedelta(days=1)

        all_dates = self._storage.get_all_dates_descending()
        eligible: list[date] = []
        for d in all_dates:
            if d == today or d == yesterday:
                continue
            month_dir = self._storage.get_month_dir(d)
            summaries = self._storage.list_summaries(month_dir)
            if not self._storage.is_covered_by_summary(d, summaries):
                eligible.append(d)

        if not eligible:
            return CompressionResult(compressed=False, reason="no_eligible_days")

        eligible.sort()
        to_compress = eligible[:7]

        daily_paths = [
            p
            for d in to_compress
            for p in self._storage.list_daily_segments(d)
        ]
        summary_text = await self._compressor.compress_to_week_summary(
            daily_paths, summarize_fn,
        )

        if not summary_text:
            return CompressionResult(compressed=False, reason="empty_summary")

        start_str = to_compress[0].strftime("%m-%d")
        end_str = to_compress[-1].strftime("%m-%d")
        summary_filename = f"week_{start_str}_to_{end_str}.summary.md"
        month_dir = self._storage.get_month_dir(to_compress[0])
        self._storage.save_summary(month_dir / summary_filename, summary_text)

        self._load_memory()

        logger.info(
            "Week summary created: %s (%d days compressed)", summary_filename, len(to_compress),
        )
        return CompressionResult(
            compressed=True,
            removed_count=len(to_compress),
            summary=summary_text[:200],
        )

    # ------------------------------------------------------------------
    # Compression: in-memory fallback (within-day overflow)
    # ------------------------------------------------------------------

    async def _try_intra_day_compression(
        self,
        summarize_fn: Callable[[str], Awaitable[str]],
        keep_ratio: float,
    ) -> CompressionResult:
        compressible = self._items[:self._turn_start]
        current_turn = self._items[self._turn_start:]

        if not compressible:
            return CompressionResult(compressed=False, reason="empty")

        items_with_context = list(compressible)
        if self._intra_day_summary:
            items_with_context.insert(0, ContextItem(
                role="system",
                content=f"之前的摘要：\n{self._intra_day_summary}",
                source="summary",
                priority=MessagePriority.HIGH,
            ))

        result = await self._compressor.compress_with_llm(
            items_with_context, keep_ratio, summarize_fn,
        )

        if not result.compressed:
            return result

        kept = compressible[-result.kept_count:] if result.kept_count > 0 else []
        self._intra_day_summary = result.summary
        self._items = kept + current_turn
        self._turn_start = len(kept)

        logger.info(
            "Intra-day compression: %d removed, %d kept, %d current-turn protected",
            result.removed_count, result.kept_count, len(current_turn),
        )
        return result

    # ------------------------------------------------------------------
    # Sanitize on load
    # ------------------------------------------------------------------

    def _sanitize_on_load(self) -> None:
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
        logger.warning("Sanitized %d incomplete tool message(s) on load", removed)
