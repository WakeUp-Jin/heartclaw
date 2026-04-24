from __future__ import annotations

import asyncio
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from config.settings import settings, get_heartclaw_home
from utils.logger import get_uvicorn_log_config, logger, set_log_level

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
from core.tool.tools.memory.memory_tools import register_memory_tools
from core.agent.agent import Agent
from scheduler.memory_updater import MemoryUpdateScheduler
from scheduler.forge_plan_scheduler import ForgePlanScheduler

from storage.short_memory_store import ShortMemoryStore
from storage.memory_store import LocalMemoryStore

from channels.feishu.channel import FeishuChannel
from channels.registry import get_all_channels, register_channel

from api.app import create_app
from api.routes.chat import set_agent, set_message_queue
from api.routes.card_callback import set_approval_store
from api.routes.ws import install_ws_log_handler
from core.queue.message_queue import MessageQueue
from core.queue.processor import QueueProcessor
from core.reply import ReplyDispatcher, FutureBackend, CliBackend, FeishuBackend
from scheduler.cron_scheduler import CronTaskScheduler
from core.agent.kairos_agent import KairosRunner

_memory_scheduler: MemoryUpdateScheduler | None = None
_forge_plan_scheduler: ForgePlanScheduler | None = None
_cron_scheduler: CronTaskScheduler | None = None
_queue_processor_task: asyncio.Task | None = None


async def startup() -> None:
    global _memory_scheduler, _forge_plan_scheduler, _cron_scheduler
    logger.info("=== HeartClaw starting ===")

    set_log_level(settings.log_level)
    install_ws_log_handler()

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

    llm_low = llm_registry.get_low()

    async def tool_summarize_fn(text: str) -> str:
        return await llm_low.simple_chat(text)

    scheduler_config = ToolSchedulerConfig(
        approval_mode=ApprovalMode.YOLO,
    )
    scheduler = ToolScheduler(
        tool_manager=tool_manager,
        approval_store=approval_store,
        summarize_fn=tool_summarize_fn,
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

    # 7.5. Message queue + reply dispatcher + KAIROS + processor + cron scheduler
    global _queue_processor_task

    queue = MessageQueue()
    set_message_queue(queue)

    reply_dispatcher = ReplyDispatcher()
    reply_dispatcher.add_backend(FutureBackend())
    reply_dispatcher.add_backend(CliBackend())

    kairos_runner: KairosRunner | None = None
    if settings.kairos.enabled:
        kairos_storage = ShortMemoryStore(base_dir=settings.kairos_memory_dir)
        kairos_runner = KairosRunner(
            llm_registry=llm_registry,
            tool_manager=tool_manager,
            scheduler=scheduler,
            kairos_storage=kairos_storage,
            long_term_memory=long_term,
            config=settings.kairos,
            short_term_dir=settings.short_term_dir,
            long_term_dir=settings.long_term_dir,
        )
        logger.info("KairosRunner created")

    processor = QueueProcessor(
        queue=queue,
        agent=agent,
        reply_dispatcher=reply_dispatcher,
        kairos_runner=kairos_runner,
        kairos_config=settings.kairos if settings.kairos.enabled else None,
    )
    _queue_processor_task = asyncio.create_task(processor.run())

    _cron_scheduler = CronTaskScheduler(queue=queue)
    await _cron_scheduler.start()

    if settings.kairos.enabled:
        logger.info("KAIROS autonomous mode enabled (tail-dispatch in QueueProcessor)")
    else:
        logger.info("KAIROS autonomous mode disabled")

    logger.info("MessageQueue + QueueProcessor + CronTaskScheduler started")

    # 8. Memory update scheduler (daily LTM updates at configured time)
    _memory_scheduler = MemoryUpdateScheduler(
        llm_low=llm_registry.get_low(),
        memory_store=memory_store,
        short_memory_store=short_memory_storage,
        update_log_dir=settings.update_log_dir,
        schedule_time=settings.memory_update_schedule,
    )
    await _memory_scheduler.start()

    # 8.5. Forge plan scheduler (daily forge plan analysis)
    _forge_plan_scheduler = ForgePlanScheduler(
        llm_low=llm_registry.get_low(),
        short_memory_store=short_memory_storage,
        schedule_time=settings.tiangong.forge_plan_schedule,
    )
    await _forge_plan_scheduler.start()

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
        from core.queue.types import QueueMessage, MessagePriority
        from core.agent.context_vars import current_chat_id

        async def on_message(text: str, chat_id: str, open_id: str) -> None:
            current_chat_id.set(chat_id)
            msg = QueueMessage(
                priority=MessagePriority.USER,
                mode="user",
                content=text,
                chat_id=chat_id,
                open_id=open_id,
                source_channel="feishu",
            )
            future = await queue.enqueue(msg)
            await future

        channel = FeishuChannel(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret,
            on_message=on_message,
        )
        await channel.connect()
        register_channel(channel)
        reply_dispatcher.add_backend(FeishuBackend(channel))
        logger.info("FeishuChannel connected (p2p single-chat)")

        async def send_card(chat_id: str, card_json: str) -> None:
            await channel.send_message(chat_id, card_json, msg_type="interactive")

        scheduler._send_card = send_card
        logger.info("Scheduler send_card callback attached")
    else:
        logger.info("Channel mode = %s, skipping Feishu (API-only mode)", settings.channel_mode)

    logger.info("=== HeartClaw ready ===")


async def shutdown() -> None:
    global _memory_scheduler, _forge_plan_scheduler, _cron_scheduler, _queue_processor_task
    logger.info("=== HeartClaw shutting down ===")

    if _cron_scheduler:
        await _cron_scheduler.stop()

    if _queue_processor_task:
        _queue_processor_task.cancel()
        try:
            await _queue_processor_task
        except asyncio.CancelledError:
            pass
        _queue_processor_task = None

    if _forge_plan_scheduler:
        await _forge_plan_scheduler.stop()

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
        log_config=get_uvicorn_log_config(settings.log_level),
    )


if __name__ == "__main__":
    main()
