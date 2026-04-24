"""Context compression strategies.

Provides LLM-based summarisation at multiple granularities:
- Week summary: from daily raw records
- Month summary: from daily records + week summaries
- Year summary: from month summaries

Also retains the legacy in-memory compression for within-day overflow.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Awaitable

from core.context.types import ContextItem, CompressionResult
from core.context.utils.token_estimator import TokenEstimator
from core.prompts.compression import (
    WEEK_PROMPT,
    MONTH_PROMPT,
    YEAR_PROMPT,
    INTRA_DAY_PROMPT,
)


class ContextCompressor:
    """Orchestrates context compression at multiple granularities."""

    def __init__(self, token_estimator: TokenEstimator | None = None):
        self._estimator = token_estimator or TokenEstimator()

    # ------------------------------------------------------------------
    # Multi-layer summary methods
    # ------------------------------------------------------------------

    async def compress_to_week_summary(
        self,
        daily_jsonl_paths: list[Path],
        summarize_fn: Callable[[str], Awaitable[str]],
    ) -> str:
        """Read consecutive daily .jsonl files and produce a week summary."""
        parts: list[str] = []
        for p in sorted(daily_jsonl_paths, key=lambda x: x.name):
            day_text = self._jsonl_to_text(p)
            if day_text:
                parts.append(f"## {p.stem}\n{day_text}")

        if not parts:
            return ""

        content = "\n\n".join(parts)
        start = daily_jsonl_paths[0].stem if daily_jsonl_paths else "?"
        end = daily_jsonl_paths[-1].stem if daily_jsonl_paths else "?"

        prompt = WEEK_PROMPT.format(
            n=len(daily_jsonl_paths),
            start=start,
            end=end,
            content=content,
        )
        return await summarize_fn(prompt)

    async def compress_to_month_summary(
        self,
        daily_jsonl_paths: list[Path],
        week_summary_texts: list[str],
        month_label: str,
        summarize_fn: Callable[[str], Awaitable[str]],
    ) -> str:
        """Combine daily records + week summaries into a month summary."""
        daily_parts: list[str] = []
        for p in sorted(daily_jsonl_paths, key=lambda x: x.name):
            day_text = self._jsonl_to_text(p)
            if day_text:
                daily_parts.append(f"## {p.stem}\n{day_text}")

        daily_content = "\n\n".join(daily_parts) if daily_parts else "(无日记录)"
        week_content = "\n\n---\n\n".join(week_summary_texts) if week_summary_texts else "(无周摘要)"

        prompt = MONTH_PROMPT.format(
            month=month_label,
            week_summaries=week_content,
            daily_content=daily_content,
        )
        return await summarize_fn(prompt)

    async def compress_to_year_summary(
        self,
        month_summary_texts: list[str],
        year_label: str,
        summarize_fn: Callable[[str], Awaitable[str]],
    ) -> str:
        """Combine month summaries into a year summary."""
        content = "\n\n---\n\n".join(month_summary_texts)
        prompt = YEAR_PROMPT.format(year=year_label, month_summaries=content)
        return await summarize_fn(prompt)

    # ------------------------------------------------------------------
    # Legacy: in-memory compression for within-day overflow
    # ------------------------------------------------------------------

    async def compress_with_llm(
        self,
        items: list[ContextItem],
        keep_ratio: float,
        summarize_fn: Callable[[str], Awaitable[str]],
    ) -> CompressionResult:
        """Compress older items via LLM summary, keeping the most recent portion."""
        if len(items) < 4:
            return CompressionResult(compressed=False, reason="too_few_messages")

        split_index = self._find_split_point(items, keep_ratio)
        split_index = self._adjust_for_tool_calls(items, split_index)

        to_compress = items[:split_index]
        to_keep = items[split_index:]

        if not to_compress:
            return CompressionResult(compressed=False, reason="nothing_to_compress")

        text = self._items_to_text(to_compress)
        prompt = INTRA_DAY_PROMPT + text

        summary = await summarize_fn(prompt)

        return CompressionResult(
            compressed=True,
            removed_count=len(to_compress),
            kept_count=len(to_keep),
            summary=summary,
        )

    def trim_tool_messages(
        self,
        items: list[ContextItem],
        keep_last_rounds: int = 3,
    ) -> list[ContextItem]:
        """Remove old tool-call rounds, keeping the most recent ones."""
        rounds = self._identify_tool_rounds(items)
        if len(rounds) <= keep_last_rounds:
            return items

        keep_indices: set[int] = set()
        for indices in rounds[-keep_last_rounds:]:
            keep_indices.update(indices)

        result: list[ContextItem] = []
        for i, item in enumerate(items):
            is_tool_related = (
                (item.role == "assistant" and item.tool_calls)
                or item.role == "tool"
            )
            if not is_tool_related or i in keep_indices:
                result.append(item)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _jsonl_to_text(path: Path) -> str:
        """Read a .jsonl file and convert to human-readable text."""
        role_labels = {"user": "用户", "assistant": "助手", "tool": "工具", "system": "系统"}
        lines: list[str] = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    item = json.loads(raw)
                    role = item.get("role", "?")
                    content = item.get("content", "")
                    label = role_labels.get(role, role)
                    if content:
                        lines.append(f"{label}: {content}")
        except Exception:
            pass
        return "\n".join(lines)

    def _find_split_point(self, items: list[ContextItem], keep_ratio: float) -> int:
        total_tokens = self._estimator.estimate_items(items)
        preserve_tokens = int(total_tokens * keep_ratio)

        accumulated = 0
        for i in range(len(items) - 1, -1, -1):
            accumulated += self._estimator.estimate_item(items[i])
            if accumulated >= preserve_tokens:
                return i
        return 0

    @staticmethod
    def _adjust_for_tool_calls(items: list[ContextItem], index: int) -> int:
        while index > 0 and items[index].role == "tool":
            index -= 1

        if (
            index < len(items)
            and items[index].role == "assistant"
            and items[index].tool_calls
        ):
            call_ids = {tc.get("id") for tc in items[index].tool_calls if tc.get("id")}
            end = index + 1
            while (
                end < len(items)
                and items[end].role == "tool"
                and items[end].tool_call_id in call_ids
            ):
                end += 1
            index = end

        return index

    @staticmethod
    def _identify_tool_rounds(items: list[ContextItem]) -> list[list[int]]:
        rounds: list[list[int]] = []
        current: list[int] = []

        for i, item in enumerate(items):
            if item.role == "assistant" and item.tool_calls:
                if current:
                    rounds.append(current)
                current = [i]
            elif item.role == "tool":
                current.append(i)

        if current:
            rounds.append(current)
        return rounds

    @staticmethod
    def _items_to_text(items: list[ContextItem]) -> str:
        role_labels = {"user": "用户", "assistant": "助手", "tool": "工具", "system": "系统"}
        parts: list[str] = []
        for item in items:
            label = role_labels.get(item.role, item.role)
            parts.append(f"{label}: {item.content or ''}")
        return "\n".join(parts)
