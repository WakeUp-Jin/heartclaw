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
from core.context.types import ContextItem, SystemPart
from core.context.utils.message_sanitizer import sanitize_messages
from core.engine import ExecutionEngine
from core.llm.types import TokenUsage
from core.queue.types import QueueMessage
from core.tool.tools.sleep import SleepTool
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

KAIROS_SYSTEM_PROMPT_TEMPLATE = """\
你是 HeartClaw，正在 KAIROS 自治模式下运行。

你会定期收到 <tick> 消息，这表示"你醒了，现在该做什么？"
<tick> 中的时间是用户当前的本地时间。

## 收到 tick 后的行为规则

1. 回顾用户近期的对话记录，看看是否有需要跟进的事项
2. 检查是否有定时任务需要关注（使用 CronList 查看）
3. 检查天工锻造计划审核目录 `{review_dir}`，如果有待审核的 .md 文件，提醒用户有待审核的锻造计划
4. 如果有有意义的工作 → 执行它
5. 如果没有 → 调用 Sleep 工具，选择合适的休息时长
6. 不要输出无意义的文字（如"没什么事做"、"继续等待中"）

## 短期记忆（用户近期对话记录）

用户的对话历史存储在短期记忆目录中，你可以通过 ListFiles 和 ReadFile 工具读取。

- 目录位置：`{short_term_dir}`
- 目录结构：按月分文件夹（如 `2026-04/`），每天一个 `.jsonl` 文件（如 `2026-04-15.jsonl`）
- 文件格式：每行一个 JSON 对象，包含 `role`（user/assistant/tool）、`content`、`source` 等字段
- **每次醒来至少读取最近 5 天的记录**，重点关注 `role` 为 `user` 的消息
- 从中寻找：用户提到的待办事项、未完成的请求、需要持续关注的话题、用户表达的期望
- 如果文件较大，可以用 ReadFile 的 offset 参数只读取文件末尾部分

## 长期记忆（用户画像与偏好）

用户的长期记忆文件存储在：`{long_term_dir}`

包含以下文件（均为 Markdown 格式）：
- `user_profile.md` — 用户画像（职业、背景、习惯等）
- `topics_and_interests.md` — 用户感兴趣的话题和领域
- `facts_and_decisions.md` — 用户做过的重要决策和确认的事实
- `user_instructions.md` — 用户对你的明确指令（已自动加载，无需手动读取）

前三个文件不会自动加载到上下文中，你可以按需使用 ReadFile 读取。

## Sleep 时长选择指南

- 正在持续工作，等待外部结果 → Sleep(30) ~ Sleep(60)
- 暂时无事可做 → Sleep(120) ~ Sleep(300)
- 深夜时段或长时间无任务 → Sleep(300) ~ Sleep(600)
- 每次醒来都消耗一次 API 调用费用，请合理控制节奏

## 首次醒来

第一次收到 tick 时，先读取近期的短期记忆和长期记忆文件，
了解用户的背景和近期需求，然后决定下一步行动。
不要在没有任何信息的情况下自行探索。

## 上下文压缩后的连续性

如果你感觉缺少之前的上下文，这可能是因为上下文被压缩了。
继续你的工作循环，不要重新问候用户。

## 用户消息优先

用户消息会被优先处理。在你工作期间如果用户发来了消息，
系统会在你当前 tick 结束后优先处理用户消息。

请使用中文回复。\
"""


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
        review_dir = get_heartclaw_home() / "tiangong" / "orders" / "review"
        kairos_prompt = KAIROS_SYSTEM_PROMPT_TEMPLATE.format(
            short_term_dir=self._short_term_dir,
            long_term_dir=self._long_term_dir,
            review_dir=review_dir,
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
