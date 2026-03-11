"""ContextManager: loading strategy, context assembly, compression trigger."""

from __future__ import annotations

from typing import Any, Callable, Awaitable, TYPE_CHECKING

from core.context.chat_store import ChatStore
from core.context.modules.system_prompt import SystemPromptContext
from utils import logger

if TYPE_CHECKING:
    from core.context.modules.memory import MemoryContext


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: Chinese ~2 chars/token, other ~4 chars/token."""
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other = len(text) - cn
    return cn // 2 + other // 4


def _estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for m in messages:
        total += _estimate_tokens(m.get("content", "") or "")
        for tc in m.get("tool_calls", []):
            fn = tc.get("function", {})
            total += _estimate_tokens(fn.get("arguments", ""))
    return total


class ContextManager:
    def __init__(
        self,
        chat_store: ChatStore,
        system_prompt: SystemPromptContext | None = None,
        memory: MemoryContext | None = None,
        max_token_estimate: int = 60000,
        compress_keep_ratio: float = 0.3,
    ):
        self._store = chat_store
        self._system_prompt = system_prompt or SystemPromptContext()
        self._memory = memory
        self._max_token_estimate = max_token_estimate
        self._compress_keep_ratio = compress_keep_ratio

        self._summary: str = ""
        self._messages: list[dict[str, Any]] = []

        self._load_session()

    # ------------------------------------------------------------------
    # Message operations (called by Agent)
    # ------------------------------------------------------------------

    def append_message(self, message: dict[str, Any]) -> None:
        """Append a message to both memory and disk."""
        self._messages.append(message)
        self._store.append(message)

    # ------------------------------------------------------------------
    # Context assembly (called by Agent before LLM)
    # ------------------------------------------------------------------

    def get_context(self) -> list[dict[str, Any]]:
        """Build LLM context: system_prompt + memory + summary(if any) + messages."""
        ctx: list[dict[str, Any]] = []

        ctx.extend(self._system_prompt.get_messages())

        if self._memory is not None:
            ctx.extend(self._memory.get_messages())

        if self._summary:
            ctx.append({
                "role": "system",
                "content": f"以下是之前对话的压缩摘要：\n\n{self._summary}",
            })

        ctx.extend(self._messages)
        return ctx

    # ------------------------------------------------------------------
    # Compression
    # ------------------------------------------------------------------

    def needs_compression(self) -> bool:
        return self.estimate_tokens() > self._max_token_estimate

    def estimate_tokens(self) -> int:
        total = _estimate_messages_tokens(self._messages)
        if self._summary:
            total += _estimate_tokens(self._summary)
        return total

    async def compress(self, summarize_fn: Callable[[str], Awaitable[str]]) -> None:
        """Compress: LLM summarizes older 70%, keep recent 30%. JSONL untouched."""
        if not self._messages:
            return

        total = len(self._messages)
        keep_count = max(2, int(total * self._compress_keep_ratio))
        compress_count = total - keep_count

        if compress_count <= 0:
            return

        to_compress = self._messages[:compress_count]
        to_keep = self._messages[compress_count:]

        parts = []
        if self._summary:
            parts.append(f"之前的摘要：\n{self._summary}\n")
        for m in to_compress:
            role = {"user": "用户", "assistant": "助手", "tool": "工具"}.get(m["role"], m["role"])
            parts.append(f"{role}: {m.get('content', '') or ''}")
        compress_text = "\n".join(parts)

        prompt = (
            "请将以下对话记录压缩为简洁的摘要，保留关键信息、用户意图、重要决策和结论。"
            "摘要应当让后续对话能理解之前的上下文。使用中文。\n\n"
            f"{compress_text}"
        )

        try:
            summary = await summarize_fn(prompt)
        except Exception as e:
            logger.error("Compression failed: %s", e)
            return

        checkpoint_line = self._store.count_lines() - keep_count
        self._store.save_checkpoint(summary, checkpoint_line)

        self._summary = summary
        self._messages = to_keep

        logger.info(
            "Compressed: %d messages -> summary + %d recent, checkpoint at line %d",
            total, keep_count, checkpoint_line,
        )

    # ------------------------------------------------------------------
    # Clear / new session
    # ------------------------------------------------------------------

    def clear_conversation(self) -> None:
        """Start a new session. Old JSONL preserved on disk."""
        self._store.new_session()
        self._messages.clear()
        self._summary = ""
        logger.info("Conversation cleared, new session started")

    # ------------------------------------------------------------------
    # Internal: session loading
    # ------------------------------------------------------------------

    def _load_session(self) -> None:
        """Load messages from disk, respecting checkpoint if present."""
        checkpoint = self._store.load_checkpoint()

        if checkpoint:
            self._summary = checkpoint.get("summary", "")
            checkpoint_line = checkpoint.get("checkpoint_line", 0)
            self._messages = self._store.load_from_line(checkpoint_line)
            logger.info(
                "Loaded session with checkpoint: summary=%d chars, %d messages from line %d",
                len(self._summary), len(self._messages), checkpoint_line,
            )
        else:
            self._summary = ""
            self._messages = self._store.load_all()
            logger.info("Loaded session: %d messages (no checkpoint)", len(self._messages))
