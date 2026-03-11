from __future__ import annotations

import asyncio

import uvicorn

from config.settings import settings
from utils import logger

from core.llm.types import LLMConfig
from core.llm.factory import create_llm_service
from core.context.chat_store import ChatStore
from core.context.manager import ContextManager
from core.context.modules.system_prompt import SystemPromptContext
from core.tool.manager import ToolManager
from core.tool.feishu.client import FeishuClient
from core.tool.feishu import register_feishu_tools
from core.tool.memory_tools import register_memory_tools
from core.agent.simple_agent import SimpleAgent

from memory.memory_store import MemoryStore
from memory.memory_context import MemoryContext

from channels.feishu.channel import FeishuChannel
from channels.registry import register_channel

from api.app import create_app
from api.routes.chat import set_agent


async def startup() -> None:
    logger.info("=== PineClaw starting ===")

    # 1. Feishu Client
    feishu_client = FeishuClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret,
    )
    logger.info("FeishuClient created")

    # 2. LLM Service
    llm_config = LLMConfig(
        provider=settings.llm_provider,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )
    llm = create_llm_service(llm_config)
    logger.info("LLM Service created: provider=%s, model=%s", llm_config.provider, llm_config.model)

    # 3. Tool Manager + register tools
    tool_manager = ToolManager()
    register_feishu_tools(tool_manager, feishu_client)
    logger.info("Feishu tools registered: %d tools", len(tool_manager.list_tools()))

    # 4. Memory Store
    memory_store = MemoryStore(
        feishu_client=feishu_client,
        folder_name=settings.feishu_memory_folder_name,
    )
    await memory_store.initialize()
    register_memory_tools(tool_manager, memory_store)
    logger.info("Memory tools registered, total: %d tools", len(tool_manager.list_tools()))

    # 5. Chat Store (persistent conversation history)
    chat_store = ChatStore(history_dir=settings.chat_history_dir)
    logger.info(
        "ChatStore initialized: dir=%s, session=%s",
        settings.chat_history_dir,
        chat_store.session_file,
    )

    # 6. Context Manager
    memory_ctx = MemoryContext(memory_store)
    context_manager = ContextManager(
        chat_store=chat_store,
        system_prompt=SystemPromptContext(),
        memory=memory_ctx,
        max_token_estimate=settings.chat_max_token_estimate,
        compress_keep_ratio=settings.chat_compress_keep_ratio,
    )
    logger.info("ContextManager created")

    # 7. Agent
    agent = SimpleAgent(
        llm=llm,
        context_manager=context_manager,
        tool_manager=tool_manager,
    )
    set_agent(agent)
    logger.info("SimpleAgent created")

    # 8. Feishu Channel
    async def on_message(text: str, chat_id: str, open_id: str) -> str:
        return await agent.run(text, chat_id, open_id)

    channel = FeishuChannel(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret,
        on_message=on_message,
    )
    await channel.connect()
    register_channel(channel)
    logger.info("FeishuChannel connected (p2p single-chat)")

    logger.info("=== PineClaw ready ===")


def main() -> None:
    app = create_app()

    @app.on_event("startup")
    async def app_startup():
        await startup()

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
