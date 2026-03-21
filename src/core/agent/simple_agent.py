from __future__ import annotations

from typing import TYPE_CHECKING

from core.llm.utils.tool_loop import execute_tool_loop
from utils.logger import get_logger
from utils.token_counter import TokenCounter

if TYPE_CHECKING:
    from core.llm.registry import LLMServiceRegistry
    from core.context.manager import ContextManager
    from core.tool.scheduler import ToolScheduler

logger = get_logger("agent")

CLEAR_COMMANDS = {"清空聊天记录", "清空历史记录", "清空对话", "/clear"}


class SimpleAgent:
    def __init__(
        self,
        llm_registry: LLMServiceRegistry,
        context_manager: ContextManager,
        scheduler: ToolScheduler,
        token_counter: TokenCounter | None = None,
    ):
        self._registry = llm_registry
        self._ctx = context_manager
        self._scheduler = scheduler
        self._token_counter = token_counter or TokenCounter()

    @property
    def token_counter(self) -> TokenCounter:
        return self._token_counter

    async def run(self, user_text: str, chat_id: str = "", open_id: str = "") -> str:
        logger.info("Agent run: user=%s, chat=%s, text=%s", open_id, chat_id, user_text[:80])

        if user_text.strip() in CLEAR_COMMANDS:
            return self._handle_clear()

        self._ctx.append_message({"role": "user", "content": user_text})

        messages = self._ctx.get_context()
        tools = self._scheduler.tool_manager.get_formatted_tools()

        llm = self._registry.get_high()
        response_text, usage, tool_messages = await execute_tool_loop(
            llm, messages, tools, self._scheduler, chat_id=chat_id,
        )

        self._token_counter.add(usage.prompt_tokens, usage.completion_tokens)

        for msg in tool_messages:
            self._ctx.append_message(msg)

        self._ctx.append_message({"role": "assistant", "content": response_text})

        logger.info(
            "Agent done: tokens=%d (p=%d, c=%d)",
            usage.total_tokens, usage.prompt_tokens, usage.completion_tokens,
        )

        if self._ctx.needs_compression():
            logger.info("Token threshold exceeded, triggering compression...")
            await self._compress_history()

        return response_text

    def _handle_clear(self) -> str:
        self._ctx.clear_conversation()
        logger.info("Chat cleared by user")
        return "聊天记录已清空，开始新的对话。"

    async def _compress_history(self) -> None:
        llm_low = self._registry.get_low()

        async def summarize_fn(text: str) -> str:
            return await llm_low.simple_chat(
                text,
                system_prompt="你是一个对话摘要助手。请将给定的对话内容压缩为简洁的摘要。",
            )

        try:
            await self._ctx.compress(summarize_fn)
            logger.info(
                "Compression done, estimated tokens now: %d",
                self._ctx.estimate_tokens(),
            )
        except Exception as e:
            logger.error("Failed to compress chat history: %s", e)
