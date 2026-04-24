"""ContextManager — unified orchestrator for all context modules.

Coordinates SystemPromptContext, LongTermMemoryContext and
ShortTermMemoryContext to build the message sequence sent to the LLM.

All message types (user input, tool calls/responses, assistant replies)
flow through ShortTermMemoryContext as a unified stream.

Each module's ``format()`` returns a ``ContextParts`` containing:
- ``system_parts``: ``SystemPart`` fragments merged into one system message.
- ``message_items``: ``ContextItem`` list placed into the conversation messages.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Awaitable

from core.context.types import (
    ContextItem, CompressionConfig, MessagePriority, PromptSegment,
    ContextParts, SystemPart,
)
from core.context.modules.system_prompt import SystemPromptContext
from core.context.modules.short_term_memory import ShortTermMemoryContext
from core.context.utils.message_sanitizer import sanitize_messages
from core.context.utils.token_estimator import TokenEstimator
from core.skill.scanner import scan_skills, build_catalog
from utils.logger import logger

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.context.modules.long_term_memory import LongTermMemoryContext

SYSTEM_PART_SEPARATOR = "\n\n"


class ContextManager:
    """Assembles the full LLM context from individual context modules."""

    def __init__(
        self,
        system_prompt: SystemPromptContext,
        short_term_memory: ShortTermMemoryContext,
        long_term_memory: LongTermMemoryContext | None = None,
        compression_config: CompressionConfig | None = None,
    ) -> None:
        self._system_prompt = system_prompt
        self._short_term = short_term_memory
        self._long_term = long_term_memory
        self._config = compression_config or CompressionConfig()
        self._estimator = TokenEstimator()

    # ------------------------------------------------------------------
    # Public API (called by Agent)
    # ------------------------------------------------------------------

    def append_item(self, item: ContextItem) -> None:
        """Append a pre-built ContextItem, preserving all metadata (usage, thinking, etc.).

        Tool-related items get their source and priority set automatically.
        All items are written to ShortTermMemory (and flushed to disk)
        immediately.
        """
        if item.tool_calls:
            item.source = item.source or "tool"
            item.priority = MessagePriority.HIGH
        elif item.role == "tool":
            item.source = item.source or "tool"
            item.priority = MessagePriority.HIGH
        self._short_term.append_message(item)

    def append_message(self, message: dict[str, Any]) -> None:
        """Append from a plain message dict (used for intermediate tool messages)."""
        item = ContextItem.from_message(message, source="conversation")
        self.append_item(item)

    def get_context(self) -> list[dict[str, Any]]:
        """组装最终的 LLM message 数组。

        1. 从各模块收集 system_parts 和 message_items
        2. 将所有 system_parts 渲染为 XML 标签并合并为一条 system message
        3. 将 message_items 逐个转为 message dict
        """
        system_parts, message_items = self._collect_parts()
        messages: list[dict[str, Any]] = []

        if system_parts:
            rendered = SYSTEM_PART_SEPARATOR.join(
                part.render() for part in system_parts if part.content.strip()
            )
            messages.append({"role": "system", "content": rendered})

        messages.extend(item.to_message() for item in message_items)
        return self._sanitize(messages)

    def needs_compression(self) -> bool:
        return self._short_term.needs_compression(
            self._config.context_window,
            self._config.compression_threshold,
        )

    async def compress(self, summarize_fn: Callable[[str], Awaitable[str]]) -> None:
        """Trigger compression on short-term memory.

        Tries disk-based week summary first, then falls back to in-memory
        compression for within-day overflow.
        """
        result = await self._short_term.compress(
            summarize_fn,
            keep_ratio=self._config.compress_keep_ratio,
        )
        if result.compressed:
            logger.info(
                "Compression done, estimated tokens now: %d",
                self.estimate_tokens(),
            )

    def estimate_tokens(self) -> int:
        items = self._build_context_items()
        return self._estimator.estimate_items(items)

    def clear_conversation(self) -> None:
        """Clear short-term memory, starting a new conversation."""
        self._short_term.clear()
        logger.info("Conversation cleared, new conversation started")

    # ------------------------------------------------------------------
    # Skill initialization
    # ------------------------------------------------------------------

    def init_skills(self, project_root: Path) -> None:
        """扫描 Skill 目录，构建 catalog 并注册为系统提示词片段。

        调用 scan_skills() 从项目级和用户级目录发现所有 SKILL.md，
        再用 build_catalog() 生成 XML 格式的目录文本，
        最后通过 SystemPromptContext.register_segment() 注入系统提示词。

        如果没有发现任何 Skill，则不注入任何内容。
        """
        skills = scan_skills(project_root)
        catalog = build_catalog(skills)
        if catalog:
            self._system_prompt.register_segment(PromptSegment(
                id="skill_catalog",
                content=catalog,
                priority=80,
            ))

    # ------------------------------------------------------------------
    # Module accessors
    # ------------------------------------------------------------------

    @property
    def system_prompt(self) -> SystemPromptContext:
        return self._system_prompt

    @property
    def short_term_memory(self) -> ShortTermMemoryContext:
        return self._short_term

    @property
    def long_term_memory(self) -> LongTermMemoryContext | None:
        return self._long_term

    # ------------------------------------------------------------------
    # Private: context assembly
    # ------------------------------------------------------------------

    def _collect_parts(self) -> tuple[list[SystemPart], list[ContextItem]]:
        """从各模块收集 system_parts 和 message_items。

        收集顺序决定了 system message 内部的段落顺序：
        1. 系统提示词（核心指令，最前面）
        2. 长期记忆（用户画像/偏好）
        3. 压缩摘要（历史背景）
        """
        all_system: list[SystemPart] = []
        all_messages: list[ContextItem] = []

        for parts in [
            self._system_prompt.format(),
            self._long_term.format() if self._long_term else ContextParts(),
            self._short_term.format(),
        ]:
            all_system.extend(parts.system_parts)
            all_messages.extend(parts.message_items)

        return all_system, all_messages

    def _build_context_items(self) -> list[ContextItem]:
        """返回 ContextItem 列表（用于 token 估算等场景）。"""
        system_parts, message_items = self._collect_parts()
        items: list[ContextItem] = []
        if system_parts:
            rendered = SYSTEM_PART_SEPARATOR.join(
                part.render() for part in system_parts if part.content.strip()
            )
            items.append(ContextItem(
                role="system",
                content=rendered,
                source="merged_system",
                priority=MessagePriority.CRITICAL,
            ))
        items.extend(message_items)
        return items

    @staticmethod
    def _sanitize(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sanitize_messages(messages)
