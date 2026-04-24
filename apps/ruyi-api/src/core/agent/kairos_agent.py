"""KairosRunner — KAIROS 自治模式的 tick 执行器。

与 Agent 并列，拥有独立的系统提示词和上下文管理：
- 系统提示词：KAIROS 专用（替换而非追加）
- 短期记忆：独立存储在 kairos/ 目录，不加载用户对话
- 长期记忆：共享（用户画像/偏好/指令）
- 工具集：与 Agent 共享 + SleepTool
- 对话历史：仅保留最近 N 轮 tick 交互
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, TYPE_CHECKING

from config.settings import KairosConfig
from config.settings import settings
from core.context.types import ContextItem, SystemPart
from core.context.utils.message_sanitizer import sanitize_messages
from core.engine import ExecutionEngine
from core.llm.types import TokenUsage
from core.queue.types import QueueMessage
from core.tool.tools.sleep import SleepTool
from core.prompts.kairos import KAIROS_SYSTEM_PROMPT_TEMPLATE
from utils.logger import get_logger

if TYPE_CHECKING:
    from core.context.modules.long_term_memory import LongTermMemoryContext
    from core.llm.registry import LLMServiceRegistry
    from core.tool.manager import ToolManager
    from core.tool.scheduler import ToolScheduler
    from storage.short_memory_store import ShortMemoryStore

logger = get_logger("kairos_runner")

SYSTEM_PART_SEPARATOR = "\n\n"
MAX_HISTORY_MESSAGES = 10


class KairosRunner:
    """处理 KAIROS tick 消息的专用执行器。"""

    def __init__(
        self,
        llm_registry: LLMServiceRegistry,
        tool_manager: ToolManager,
        scheduler: ToolScheduler,
        kairos_storage: ShortMemoryStore,
        long_term_memory: LongTermMemoryContext,
        config: KairosConfig,
        short_term_dir: Path,
        long_term_dir: Path,
    ) -> None:
        self._registry = llm_registry
        self._tool_manager = tool_manager
        self._scheduler = scheduler
        self._storage = kairos_storage
        self._long_term = long_term_memory
        self._config = config
        self._short_term_dir = short_term_dir
        self._long_term_dir = long_term_dir
        self._engine = ExecutionEngine(scheduler=scheduler)

        self._recent_history: list[dict[str, Any]] = []

        self._register_sleep_tool()
        self._load_history()

    async def handle_tick(self, msg: QueueMessage) -> str:
        """处理一次 tick，返回 LLM 回复文本。"""
        tick_content = msg.content

        self._persist(ContextItem(role="user", content=tick_content, source="tick"))

        messages = self._build_context(tick_content)
        tools = self._tool_manager.get_formatted_tools()
        llm = self._registry.get_high()

        result = await self._engine.run(
            llm, messages, tools,
            on_message=lambda m: self._persist(ContextItem.from_message(m, source="engine")),
        )

        self._persist(ContextItem(
            role="assistant", content=result.text, source="llm",
            thinking=result.thinking,
        ))

        self._update_history(tick_content, result.text)

        logger.info(
            "Tick done: tokens=%d (p=%d, c=%d)",
            result.usage.total_tokens,
            result.usage.prompt_tokens,
            result.usage.completion_tokens,
        )
        return result.text

    def get_sleep_seconds(self, result_text: str) -> int:
        """从最近的工具调用记录中提取 Sleep 秒数。

        如果 LLM 没有调用 Sleep 工具，返回配置的默认值。
        """
        for msg in reversed(self._recent_history):
            for tc in msg.get("tool_calls", []):
                func = tc.get("function", {})
                if func.get("name") == "Sleep":
                    try:
                        args = json.loads(func.get("arguments", "{}"))
                        seconds = int(args.get("seconds", self._config.default_sleep_seconds))
                        return max(
                            self._config.min_sleep_seconds,
                            min(seconds, self._config.max_sleep_seconds),
                        )
                    except (json.JSONDecodeError, ValueError, TypeError):
                        pass
        return self._config.default_sleep_seconds

    # ------------------------------------------------------------------
    # Context assembly
    # ------------------------------------------------------------------

    def _build_context(self, tick_content: str) -> list[dict[str, Any]]:
        """组装 KAIROS tick 的精简上下文。"""
        from config.settings import get_heartclaw_home
        home = get_heartclaw_home()
        tiangong_dir = home / "tiangong"
        review_dir = tiangong_dir / "orders" / "review"
        kairos_prompt = KAIROS_SYSTEM_PROMPT_TEMPLATE.format(
            short_term_dir=self._short_term_dir,
            long_term_dir=self._long_term_dir,
            review_dir=review_dir,
            pending_dir=tiangong_dir / "orders" / "pending",
            runtime_dir=tiangong_dir / "runtime",
            active_task_path=tiangong_dir / "runtime" / "active_task.json",
            cancel_requests_dir=tiangong_dir / "runtime" / "cancel_requests",
            agent_log_tail_lines=settings.tiangong.agent_log_tail_lines,
        )
        system_parts = [kairos_prompt]

        ltm_parts = self._long_term.format()
        for part in ltm_parts.system_parts:
            system_parts.append(part.render())

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PART_SEPARATOR.join(system_parts)},
        ]

        messages.extend(self._recent_history[-MAX_HISTORY_MESSAGES:])
        messages.append({"role": "user", "content": tick_content})

        return sanitize_messages(messages)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, item: ContextItem) -> None:
        """写入 kairos/ 目录的 .jsonl 文件。"""
        try:
            self._storage.append(item.to_dict())
        except Exception:
            logger.error("Failed to persist kairos message", exc_info=True)

    def _update_history(self, tick_content: str, reply: str) -> None:
        """更新内存中的最近 tick 交互记录。"""
        self._recent_history.append({"role": "user", "content": tick_content})
        self._recent_history.append({"role": "assistant", "content": reply})
        if len(self._recent_history) > MAX_HISTORY_MESSAGES:
            self._recent_history = self._recent_history[-MAX_HISTORY_MESSAGES:]

    def _load_history(self) -> None:
        """启动时从磁盘恢复最近的 tick 交互历史。"""
        try:
            today = date.today()
            raw = self._storage.load_daily(today)
            if not raw:
                logger.info("No kairos history found for today")
                return

            items = [ContextItem.from_dict(d) for d in raw]
            messages = [item.to_message() for item in items]
            cleaned = sanitize_messages(messages)
            self._recent_history = cleaned[-MAX_HISTORY_MESSAGES:]
            logger.info(
                "Loaded %d kairos history messages from disk",
                len(self._recent_history),
            )
        except Exception:
            logger.error("Failed to load kairos history", exc_info=True)
            self._recent_history = []

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_sleep_tool(self) -> None:
        """将 SleepTool 注册到工具管理器。"""
        if not self._tool_manager.has_tool("Sleep"):
            self._tool_manager.register(SleepTool)
            logger.info("SleepTool registered for KAIROS mode")
