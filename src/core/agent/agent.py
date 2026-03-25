from __future__ import annotations

from typing import TYPE_CHECKING

from config.settings import settings
from core.engine import ExecutionEngine
from core.context.types import ContextItem, ItemUsage, MessagePriority
from core.tool.tools.bash import BashTool
from core.tool.tools.read_file import ReadFileTool
from core.tool.tools.list_files import ListFilesTool
from utils.logger import get_logger
from utils.token_counter import TokenCounter

if TYPE_CHECKING:
    from core.llm.registry import LLMServiceRegistry
    from core.context.manager import ContextManager
    from core.tool.manager import ToolManager
    from core.tool.scheduler import ToolScheduler

logger = get_logger("agent")

CLEAR_COMMANDS = {"清空聊天记录", "清空历史记录", "清空对话", "/clear"}


class Agent:
    def __init__(
        self,
        llm_registry: LLMServiceRegistry,
        context_manager: ContextManager,
        tool_manager: ToolManager,
        scheduler: ToolScheduler,
        token_counter: TokenCounter | None = None,
    ):
        self._registry = llm_registry
        self._ctx = context_manager
        self._tool_manager = tool_manager
        self._scheduler = scheduler
        self._token_counter = token_counter or TokenCounter()

        self._register_tools()

        self._engine = ExecutionEngine(scheduler=scheduler)

    @property
    def token_counter(self) -> TokenCounter:
        return self._token_counter

    async def run(self, user_text: str, chat_id: str = "", open_id: str = "") -> str:
        logger.info("Agent run: user=%s, chat=%s, text=%s", open_id, chat_id, user_text[:80])

        if user_text.strip() in CLEAR_COMMANDS:
            return self._handle_clear()

        user_item = ContextItem(
            role="user",
            content=user_text,
            source="user",
            priority=MessagePriority.HIGH,
        )
        self._ctx.append_item(user_item)

        messages = self._ctx.get_context()
        tools = self._tool_manager.get_formatted_tools()
        llm = self._registry.get_high()

        result = await self._engine.run(llm, messages, tools, chat_id=chat_id)

        self._token_counter.add(result.usage.prompt_tokens, result.usage.completion_tokens)

        for msg in result.intermediate_messages:
            self._ctx.append_message(msg)

        self._ctx.archive_tool_context()

        model_cfg = settings.get_model_config("high")
        cost = model_cfg.calc_cost(result.usage)

        assistant_item = ContextItem(
            role="assistant",
            content=result.text,
            source="llm",
            priority=MessagePriority.HIGH,
            thinking=result.thinking,
            usage=ItemUsage(
                prompt_tokens=result.usage.prompt_tokens,
                completion_tokens=result.usage.completion_tokens,
                cached_tokens=result.usage.cached_tokens,
                total_tokens=result.usage.total_tokens,
                cost=cost,
            ),
        )
        self._ctx.append_item(assistant_item)

        logger.info(
            "Agent done: tokens=%d (p=%d, c=%d, cache=%d), cost=%.6f CNY",
            result.usage.total_tokens,
            result.usage.prompt_tokens,
            result.usage.completion_tokens,
            result.usage.cached_tokens,
            cost,
        )

        if self._ctx.needs_compression():
            logger.info("Token threshold exceeded, triggering compression...")
            await self._compress_history()

        return result.text

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _register_tools(self) -> None:
        """注册 tools/ 目录下的内置工具。"""
        self._tool_manager.register(ReadFileTool)
        self._tool_manager.register(BashTool)
        self._tool_manager.register(ListFilesTool)
        logger.info("Built-in tools registered: %s", self._tool_manager.list_tools())

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
