"""Context compression strategies.

Provides LLM-based summarisation and tool-message trimming to keep the
context window within budget.
"""

from __future__ import annotations

from typing import Any, Callable, Awaitable

from core.context.types import ContextItem, CompressionResult
from core.context.utils.token_estimator import TokenEstimator


COMPRESSION_PROMPT = (
    "请将以下对话记录压缩为简洁的摘要。\n\n"
    "要求：\n"
    "- 保留所有关键决策和结论\n"
    "- 保留涉及的文件路径和代码变更\n"
    "- 保留未完成的任务和计划\n"
    "- 保留用户的偏好和约束条件\n"
    "- 删除重复信息和不重要的对话\n"
    "- 使用简洁的描述性语言\n\n"
)


class ContextCompressor:
    """Orchestrates context compression using multiple strategies."""

    def __init__(self, token_estimator: TokenEstimator | None = None):
        self._estimator = token_estimator or TokenEstimator()

    async def compress_with_llm(
        self,
        items: list[ContextItem],
        keep_ratio: float,
        summarize_fn: Callable[[str], Awaitable[str]],
    ) -> CompressionResult:
        """Compress older items via LLM summary, keeping the most recent *keep_ratio*.

        Returns a ``CompressionResult`` with the generated summary text.  The
        caller is responsible for replacing the item list.
        """
        if len(items) < 4:
            return CompressionResult(compressed=False, reason="too_few_messages")

        split_index = self._find_split_point(items, keep_ratio)
        split_index = self._adjust_for_tool_calls(items, split_index)

        to_compress = items[:split_index]
        to_keep = items[split_index:]

        if not to_compress:
            return CompressionResult(compressed=False, reason="nothing_to_compress")

        text = self._items_to_text(to_compress)
        prompt = COMPRESSION_PROMPT + text

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
        """Remove old tool-call rounds, keeping the most recent *keep_last_rounds*."""
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

    def _find_split_point(self, items: list[ContextItem], keep_ratio: float) -> int:
        """Walk backward and accumulate tokens until *keep_ratio* is reached."""
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
        """Ensure we don't split inside a tool_call <-> tool response pair."""
        # If landing on a tool response, walk backward past the whole pair
        while index > 0 and items[index].role == "tool":
            index -= 1

        # If now on an assistant with tool_calls, include all subsequent tool responses
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
        """Group indices into tool-call rounds (assistant + tool responses)."""
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
