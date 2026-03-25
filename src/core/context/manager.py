"""ContextManager — unified orchestrator for all context modules.

Coordinates SystemPromptContext, LongTermMemoryContext, ShortTermMemoryContext
and ToolContext to build the message sequence sent to the LLM.

Internally every module works with ``ContextItem``; the public
``get_context()`` method converts the assembled items into plain message
dicts via ``_to_messages()``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Awaitable

from core.context.types import ContextItem, CompressionConfig, MessagePriority, PromptSegment
from core.context.modules.system_prompt import SystemPromptContext
from core.context.modules.short_term_memory import ShortTermMemoryContext
from core.context.modules.tool_context import ToolContext
from core.context.utils.message_sanitizer import sanitize_messages
from core.context.utils.token_estimator import TokenEstimator
from core.skill.scanner import scan_skills, build_catalog
from utils import logger

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.context.modules.long_term_memory import LongTermMemoryContext


class ContextManager:
    """Assembles the full LLM context from individual context modules."""

    def __init__(
        self,
        system_prompt: SystemPromptContext,
        short_term_memory: ShortTermMemoryContext,
        tool_context: ToolContext | None = None,
        long_term_memory: LongTermMemoryContext | None = None,
        compression_config: CompressionConfig | None = None,
    ) -> None:
        self._system_prompt = system_prompt
        self._short_term = short_term_memory
        self._tool_context = tool_context or ToolContext()
        self._long_term = long_term_memory
        self._config = compression_config or CompressionConfig()
        self._estimator = TokenEstimator()

    # ------------------------------------------------------------------
    # Public API (called by Agent)
    # ------------------------------------------------------------------

    def append_item(self, item: ContextItem) -> None:
        """Append a pre-built ContextItem, preserving all metadata (usage, thinking, etc.)."""
        if item.tool_calls:
            item.source = item.source or "tool"
            item.priority = MessagePriority.HIGH
            self._tool_context.add_tool_call(item)
        elif item.role == "tool":
            item.source = item.source or "tool"
            item.priority = MessagePriority.HIGH
            self._tool_context.add_tool_response(item)
        else:
            self._short_term.append_message(item)

    def append_message(self, message: dict[str, Any]) -> None:
        """Append from a plain message dict (used for intermediate tool messages)."""
        item = ContextItem.from_message(message, source="conversation")
        self.append_item(item)

    def get_context(self) -> list[dict[str, Any]]:
        """Build the full LLM context: assemble ContextItems then convert to
        message dicts."""
        items = self._build_context_items()
        return self._to_messages(items)

    def needs_compression(self) -> bool:
        return self._short_term.needs_compression(
            self._config.context_window,
            self._config.compression_threshold,
        )

    async def compress(self, summarize_fn: Callable[[str], Awaitable[str]]) -> None:
        """Trigger compression on short-term memory."""
        # Archive any pending tool context first
        if not self._tool_context.is_empty():
            self._tool_context.archive_to(self._short_term)

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
        """Clear short-term memory and tool context, starting a new conversation."""
        self._short_term.clear()
        self._tool_context.clear()
        logger.info("Conversation cleared, new conversation started")

    def archive_tool_context(self) -> None:
        """Archive current tool context into short-term memory.

        Called by the Agent after the tool loop completes for a turn.
        """
        if not self._tool_context.is_empty():
            self._tool_context.archive_to(self._short_term)

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
    def tool_context(self) -> ToolContext:
        return self._tool_context

    @property
    def long_term_memory(self) -> LongTermMemoryContext | None:
        return self._long_term

    # ------------------------------------------------------------------
    # Private: context assembly
    # ------------------------------------------------------------------

    def _build_context_items(self) -> list[ContextItem]:
        """Assemble items in canonical order:
        1. system prompt
        2. long-term memory
        3. short-term memory (summary + history)
        4. tool context (current turn)
        """
        items: list[ContextItem] = []

        items.extend(self._system_prompt.format())

        if self._long_term is not None:
            items.extend(self._long_term.format())

        items.extend(self._short_term.format())

        items.extend(self._tool_context.format())

        return items

    def _to_messages(self, items: list[ContextItem]) -> list[dict[str, Any]]:
        """Convert ContextItem list to message dicts and sanitise."""
        messages = [item.to_message() for item in items]
        return self._sanitize(messages)

    @staticmethod
    def _sanitize(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sanitize_messages(messages)
