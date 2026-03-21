from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from config.settings import settings
from utils.logger import logger, set_log_level

from core.llm.registry import LLMServiceRegistry
from core.context.manager import ContextManager
from core.context.types import CompressionConfig
from core.context.modules.system_prompt import SystemPromptContext
from core.context.modules.long_term_memory import LongTermMemoryContext
from core.context.modules.short_term_memory import ShortTermMemoryContext
from core.context.modules.tool_context import ToolContext
from core.context.storage.jsonl_store import JsonlContextStorage
from core.context.utils.compressor import ContextCompressor
from core.tool.manager import ToolManager
from core.tool.scheduler import ToolScheduler, ToolSchedulerConfig
from core.tool.approval import ApprovalStore
from core.tool.types import ApprovalMode
from core.tool.feishu.client import FeishuClient
from core.tool.feishu import register_feishu_tools
from core.tool.memory_tools import register_memory_tools
from core.agent.simple_agent import SimpleAgent

from memory.memory_store import MemoryStore

from channels.feishu.channel import FeishuChannel
from channels.registry import get_all_channels, register_channel

from api.app import create_app
from api.routes.chat import set_agent
from api.routes.card_callback import set_approval_store


async def startup() -> None:
    logger.info("=== PineClaw starting ===")

    set_log_level(settings.log_level)

    # 1. Feishu Client
    feishu_client = FeishuClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret,
    )
    logger.info("FeishuClient created")

    # 2. LLM Service Registry
    llm_registry = LLMServiceRegistry(settings)
    llm_registry.get_high()
    llm_registry.get_low()
    logger.info("LLMServiceRegistry initialized (HIGH + LOW preloaded)")

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

    # 5. Context modules
    storage = JsonlContextStorage(history_dir=settings.chat_history_dir)
    logger.info(
        "JsonlContextStorage initialized: dir=%s, session=%s",
        settings.chat_history_dir,
        storage.session_file,
    )

    compressor = ContextCompressor()
    short_term = ShortTermMemoryContext(storage=storage, compressor=compressor)
    long_term = LongTermMemoryContext(memory_store=memory_store)
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
        long_term_memory=long_term,
        compression_config=compression_config,
    )
    logger.info("ContextManager created")

    # 7. Approval Store + Tool Scheduler
    approval_store = ApprovalStore()
    set_approval_store(approval_store)

    scheduler_config = ToolSchedulerConfig(
        approval_mode=ApprovalMode.YOLO,
    )
    scheduler = ToolScheduler(
        tool_manager=tool_manager,
        approval_store=approval_store,
        config=scheduler_config,
    )
    logger.info("ToolScheduler created (mode=%s)", scheduler_config.approval_mode.value)

    # 8. Agent
    agent = SimpleAgent(
        llm_registry=llm_registry,
        context_manager=context_manager,
        scheduler=scheduler,
    )
    set_agent(agent)
    logger.info("SimpleAgent created")

    # 9. Feishu Channel
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

    # 10. 注入 send_card 回调给 Scheduler（channel 准备好后）
    async def send_card(chat_id: str, card_json: str) -> None:
        await channel.send_message(chat_id, card_json, msg_type="interactive")

    scheduler._send_card = send_card
    logger.info("Scheduler send_card callback attached")

    logger.info("=== PineClaw ready ===")


async def shutdown() -> None:
    logger.info("=== PineClaw shutting down ===")

    channels = get_all_channels()
    for name, channel in channels.items():
        try:
            await channel.disconnect()
            logger.info("Channel disconnected: %s", name)
        except Exception:
            logger.error("Failed to disconnect channel: %s", name, exc_info=True)

    logger.info("=== PineClaw stopped ===")


def main() -> None:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await startup()
        try:
            yield
        finally:
            await shutdown()

    app = create_app(lifespan=lifespan)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
