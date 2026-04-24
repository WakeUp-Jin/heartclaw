"""Context module type definitions.

Provides the core data structures used throughout the context system:
ContextItem as the internal representation, plus configuration and result types.

Two serialisation formats exist for ContextItem:
- ``to_message()`` / ``from_message()``: LLM API format (role/content/tool_calls only).
- ``to_dict()`` / ``from_dict()``: Full persistence format (all metadata + thinking + usage).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class MessagePriority(IntEnum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class ItemUsage:
    """Token usage and cost for a single context item.

    Only populated on assistant messages (one LLM call = one usage record).
    User messages keep all fields at zero.
    """
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens,
            "total_tokens": self.total_tokens,
            "cost": self.cost,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ItemUsage:
        return cls(
            prompt_tokens=d.get("prompt_tokens", 0),
            completion_tokens=d.get("completion_tokens", 0),
            cached_tokens=d.get("cached_tokens", 0),
            total_tokens=d.get("total_tokens", 0),
            cost=d.get("cost", 0.0),
        )


@dataclass
class ContextItem:
    """Rich data structure for internal context flow.

    All context modules store and manipulate ContextItems internally.
    Use ``to_message()`` for the LLM API dict, ``to_dict()`` for persistence.
    """

    role: str
    content: str | None = None
    source: str = ""
    priority: int = MessagePriority.NORMAL
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    # tool-related fields
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None

    # thinking (model reasoning chain, must be echoed back when present)
    thinking: str | None = None
    thinking_token_estimate: int = 0

    # token usage + cost (only meaningful on assistant messages)
    usage: ItemUsage = field(default_factory=ItemUsage)

    # ------------------------------------------------------------------
    # LLM API format (minimal, only fields the model recognises)
    # ------------------------------------------------------------------

    def to_message(self) -> dict[str, Any]:
        """Convert to OpenAI chat message dict format.

        When the model has thinking enabled, ``reasoning_content`` must be
        echoed back in assistant messages that contain tool_calls, otherwise
        the API will reject the request with a 400 error.
        """
        msg: dict[str, Any] = {"role": self.role}

        if self.content is not None:
            msg["content"] = self.content

        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls

        if self.tool_call_id is not None:
            msg["tool_call_id"] = self.tool_call_id

        if self.name is not None:
            msg["name"] = self.name

        if self.thinking is not None:
            msg["reasoning_content"] = self.thinking

        return msg

    @classmethod
    def from_message(
        cls,
        message: dict[str, Any],
        *,
        source: str = "",
        priority: int = MessagePriority.NORMAL,
    ) -> ContextItem:
        """Create a ContextItem from an OpenAI chat message dict."""
        return cls(
            role=message.get("role", "user"),
            content=message.get("content"),
            source=source,
            priority=priority,
            tool_calls=message.get("tool_calls", []),
            tool_call_id=message.get("tool_call_id"),
            name=message.get("name"),
        )

    # ------------------------------------------------------------------
    # Persistence format (full metadata, used by ShortMemoryStore)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Full serialisation for JSONL persistence."""
        return {
            "role": self.role,
            "content": self.content,
            "source": self.source,
            "priority": self.priority,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "tool_calls": self.tool_calls,
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "thinking": self.thinking,
            "thinking_token_estimate": self.thinking_token_estimate,
            "usage": self.usage.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ContextItem:
        """Restore from a JSONL line (persistence format)."""
        usage_raw = d.get("usage")
        if isinstance(usage_raw, dict):
            usage = ItemUsage.from_dict(usage_raw)
        else:
            usage = ItemUsage()

        return cls(
            role=d.get("role", "user"),
            content=d.get("content"),
            source=d.get("source", ""),
            priority=d.get("priority", MessagePriority.NORMAL),
            created_at=d.get("created_at", 0.0),
            metadata=d.get("metadata", {}),
            tool_calls=d.get("tool_calls", []),
            tool_call_id=d.get("tool_call_id"),
            name=d.get("name"),
            thinking=d.get("thinking"),
            thinking_token_estimate=d.get("thinking_token_estimate", 0),
            usage=usage,
        )


@dataclass
class PromptSegment:
    """A segment of system prompt with identity and priority.

    Segments are assembled in descending priority order (higher = earlier in prompt).
    """

    id: str
    content: str
    priority: int = 5
    enabled: bool = True


@dataclass
class CompressionConfig:
    """Configuration for context compression behaviour.

    ``context_window`` comes from the active model's config, not hardcoded.
    Compression triggers when token usage >= context_window * compression_threshold.
    """

    context_window: int = 128000
    compression_threshold: float = 0.85
    compress_keep_ratio: float = 0.3
    initial_load_ratio: float = 0.60
    days_per_week_summary: int = 7

    @property
    def trigger_tokens(self) -> int:
        """Token count that triggers compression."""
        return int(self.context_window * self.compression_threshold)


@dataclass
class CompressionResult:
    """Result of a compression operation."""

    compressed: bool
    removed_count: int = 0
    kept_count: int = 0
    summary: str = ""
    reason: str = ""


@dataclass
class SystemPart:
    """一段 system 级内容，最终合并进唯一的 system message。

    tag: XML 标签名（如 "long_term_memory"），用于包裹内容
    description: 对这段内容的说明，会写入 XML 标签的 description 属性
    content: 实际内容文本
    """

    tag: str
    description: str
    content: str

    def render(self) -> str:
        """渲染为带 XML 标签的文本段落。"""
        if self.description:
            return f'<{self.tag} description="{self.description}">\n{self.content}\n</{self.tag}>'
        return f"<{self.tag}>\n{self.content}\n</{self.tag}>"


@dataclass
class ContextParts:
    """模块 format() 的返回类型，区分内容的投递目标。

    system_parts: 带标签的文本段落，最终合并进唯一的 system message。
    message_items: ContextItem 列表，作为独立 message 放入对话列表。
    """

    system_parts: list[SystemPart] = field(default_factory=list)
    message_items: list[ContextItem] = field(default_factory=list)
