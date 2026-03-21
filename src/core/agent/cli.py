"""交互式 CLI — 用于本地测试 Agent 的对话循环。

用法:
    cd src && python -m core.agent.cli
"""

from __future__ import annotations

import asyncio
import sys

from config.settings import settings
from utils.logger import logger, set_log_level

from core.llm.registry import LLMServiceRegistry
from core.context.manager import ContextManager
from core.context.types import CompressionConfig
from core.context.modules.system_prompt import SystemPromptContext
from core.context.modules.short_term_memory import ShortTermMemoryContext
from core.context.modules.tool_context import ToolContext
from core.context.utils.compressor import ContextCompressor
from core.tool.manager import ToolManager
from core.tool.scheduler import ToolScheduler, ToolSchedulerConfig
from core.tool.approval import ApprovalStore
from core.tool.types import ApprovalMode
from core.agent.agent import Agent

from storage.conversation_store import ConversationStore


def _build_agent() -> Agent:
    set_log_level(settings.log_level)

    llm_registry = LLMServiceRegistry(settings)

    tool_manager = ToolManager()

    conversation_storage = ConversationStore(base_dir=settings.conversations_dir)
    compressor = ContextCompressor()
    short_term = ShortTermMemoryContext(storage=conversation_storage, compressor=compressor)
    system_prompt = SystemPromptContext()
    tool_context = ToolContext()

    compression_config = CompressionConfig(
        max_token_estimate=settings.chat_max_token_estimate,
        compress_keep_ratio=settings.chat_compress_keep_ratio,
    )

    context_manager = ContextManager(
        system_prompt=system_prompt,
        short_term_memory=short_term,
        tool_context=tool_context,
        compression_config=compression_config,
    )

    approval_store = ApprovalStore()
    scheduler = ToolScheduler(
        tool_manager=tool_manager,
        approval_store=approval_store,
        config=ToolSchedulerConfig(approval_mode=ApprovalMode.YOLO),
    )

    return Agent(
        llm_registry=llm_registry,
        context_manager=context_manager,
        tool_manager=tool_manager,
        scheduler=scheduler,
    )


async def _repl(agent: Agent) -> None:
    print("\n🌲 PineClaw CLI (输入 /quit 退出, /clear 清空对话)\n")

    while True:
        try:
            user_input = input("You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not user_input:
            continue
        if user_input in {"/quit", "/exit", "exit", "quit"}:
            print("Bye!")
            break

        try:
            reply = await agent.run(user_input, chat_id="cli", open_id="cli-user")
        except Exception as e:
            logger.error("Agent error: %s", e, exc_info=True)
            print(f"\n[Error] {e}\n")
            continue

        print(f"\nAgent > {reply}\n")

        tc = agent.token_counter
        print(f"  [tokens: prompt={tc.prompt_tokens}, completion={tc.completion_tokens}, calls={tc.total_calls}]\n")


def main() -> None:
    agent = _build_agent()
    asyncio.run(_repl(agent))


if __name__ == "__main__":
    main()
