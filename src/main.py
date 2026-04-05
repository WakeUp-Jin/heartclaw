from __future__ import annotations

import shutil
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from config.settings import settings, get_heartclaw_home
from utils.logger import logger, set_log_level

from core.llm.registry import LLMServiceRegistry
from core.context.manager import ContextManager
from core.context.types import CompressionConfig
from core.context.modules.system_prompt import SystemPromptContext
from core.context.modules.long_term_memory import LongTermMemoryContext
from core.context.modules.short_term_memory import ShortTermMemoryContext
from core.context.utils.compressor import ContextCompressor
from core.tool.manager import ToolManager
from core.tool.scheduler import ToolScheduler, ToolSchedulerConfig
from core.tool.approval import ApprovalStore
from core.tool.types import ApprovalMode
from core.tool.memory_tools import register_memory_tools
from core.agent.agent import Agent
from scheduler.memory_updater import MemoryUpdateScheduler

from storage.short_memory_store import ShortMemoryStore
from storage.memory_store import LocalMemoryStore

from channels.feishu.channel import FeishuChannel
from channels.registry import get_all_channels, register_channel

from api.app import create_app
from api.routes.chat import set_agent
from api.routes.card_callback import set_approval_store

_memory_scheduler: MemoryUpdateScheduler | None = None


async def startup() -> None:
    global _memory_scheduler
    logger.info("=== HeartClaw starting ===")

    set_log_level(settings.log_level)

    # 1. LLM Service Registry
    llm_registry = LLMServiceRegistry(settings)
    llm_registry.get_high()
    llm_registry.get_low()
    logger.info("LLMServiceRegistry initialized (HIGH + LOW preloaded)")

    # 2. Tool Manager
    tool_manager = ToolManager()

    # 3. Local Memory Store (4 files under skills/memory/long_term/)
    memory_store = LocalMemoryStore(base_dir=str(settings.long_term_dir))
    register_memory_tools(tool_manager, memory_store)
    logger.info("Memory tools registered, total: %d tools", len(tool_manager.list_tools()))

    # 4. Short-term memory store (daily .jsonl under skills/memory/short_term/)
    short_memory_storage = ShortMemoryStore(base_dir=settings.short_term_dir)
    logger.info("ShortMemoryStore initialized: dir=%s", settings.short_term_dir)

    # 5. Context modules
    high_model = settings.get_model_config("high")

    compressor = ContextCompressor()
    short_term = ShortTermMemoryContext(
        storage=short_memory_storage,
        compressor=compressor,
        context_window=high_model.context_window,
        initial_load_ratio=settings.initial_load_ratio,
    )
    long_term = LongTermMemoryContext(memory_store=memory_store)
    system_prompt = SystemPromptContext()

    compression_config = CompressionConfig(
        context_window=high_model.context_window,
        compression_threshold=settings.compression_threshold,
        compress_keep_ratio=settings.compress_keep_ratio,
        initial_load_ratio=settings.initial_load_ratio,
    )

    context_manager = ContextManager(
        system_prompt=system_prompt,
        short_term_memory=short_term,
        long_term_memory=long_term,
        compression_config=compression_config,
    )
    logger.info("ContextManager created")

    # 6. Approval Store + Tool Scheduler
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

    # 7. Agent
    agent = Agent(
        llm_registry=llm_registry,
        context_manager=context_manager,
        tool_manager=tool_manager,
        scheduler=scheduler,
    )
    set_agent(agent)
    logger.info("Agent created")

    # 8. Memory update scheduler (daily LTM updates at configured time)
    _memory_scheduler = MemoryUpdateScheduler(
        llm_low=llm_registry.get_low(),
        memory_store=memory_store,
        short_memory_store=short_memory_storage,
        update_log_dir=settings.update_log_dir,
        schedule_time=settings.memory_update_schedule,
    )
    await _memory_scheduler.start()

    # 9. Clean up old memory directory (migrated to skills/memory/)
    old_memory_dir = get_heartclaw_home() / "memory"
    if old_memory_dir.is_dir():
        try:
            shutil.rmtree(old_memory_dir)
            logger.info("Removed legacy memory directory: %s", old_memory_dir)
        except Exception as e:
            logger.warning("Failed to remove legacy memory dir: %s", e)

    # 10. Channel (controlled by HEARTCLAW_CHANNEL_MODE)
    if settings.channel_mode == "feishu":
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

        async def send_card(chat_id: str, card_json: str) -> None:
            await channel.send_message(chat_id, card_json, msg_type="interactive")

        scheduler._send_card = send_card
        logger.info("Scheduler send_card callback attached")
    else:
        logger.info("Channel mode = %s, skipping Feishu (API-only mode)", settings.channel_mode)

    logger.info("=== HeartClaw ready ===")


async def shutdown() -> None:
    global _memory_scheduler
    logger.info("=== HeartClaw shutting down ===")

    if _memory_scheduler:
        await _memory_scheduler.stop()

    channels = get_all_channels()
    for name, channel in channels.items():
        try:
            await channel.disconnect()
            logger.info("Channel disconnected: %s", name)
        except Exception:
            logger.error("Failed to disconnect channel: %s", name, exc_info=True)

    logger.info("=== HeartClaw stopped ===")


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
