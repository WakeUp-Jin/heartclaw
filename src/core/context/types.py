"""Context module type definitions.

Provides the core data structures used throughout the context system:
ContextItem as the internal representation, plus configuration and result types.
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
class ContextItem:
    """Rich data structure for internal context flow.

    All context modules store and manipulate ContextItems internally.
    Use ``to_message()`` to convert to the dict format expected by LLM APIs.
    """

    role: str
    content: str | None = None
    source: str = ""
    priority: int = MessagePriority.NORMAL
    created_at: float = field(default_factory=time.time)
    token_estimate: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    # tool-related fields
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None

    def to_message(self) -> dict[str, Any]:
        """Convert to OpenAI chat message dict format."""
        msg: dict[str, Any] = {"role": self.role}

        if self.content is not None:
            msg["content"] = self.content

        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls

        if self.tool_call_id is not None:
            msg["tool_call_id"] = self.tool_call_id

        if self.name is not None:
            msg["name"] = self.name

        return msg

    @classmethod
    def from_message(cls, message: dict[str, Any], *, source: str = "", priority: int = MessagePriority.NORMAL) -> ContextItem:
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
    """Configuration for context compression behaviour."""

    max_token_estimate: int = 60000
    compression_threshold: float = 0.7
    overflow_threshold: float = 0.95
    compress_keep_ratio: float = 0.3


@dataclass
class CompressionResult:
    """Result of a compression operation."""

    compressed: bool
    removed_count: int = 0
    kept_count: int = 0
    summary: str = ""
    reason: str = ""
