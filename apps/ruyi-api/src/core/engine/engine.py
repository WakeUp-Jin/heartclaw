"""ExecutionEngine — LLM + Tool 循环的核心执行引擎。

实现 LLM -> tool_calls -> ToolScheduler -> repeat 的主循环，
直到 LLM 返回纯文本或达到最大迭代次数。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

from core.llm.types import LLMResponse, TokenUsage
from core.tool.types import ToolCallStatus
from utils.logger import get_logger

logger = get_logger("engine")

if TYPE_CHECKING:
    from core.llm.services.base import BaseLLMService
    from core.tool.scheduler import ToolScheduler

MAX_ITERATIONS = 10


@dataclass
class EngineResult:
    """Result of a full LLM-Tool execution loop."""
    text: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)
    thinking: str | None = None


class ExecutionEngine:
    """LLM + Tool 循环执行引擎。

    每轮: LLM.complete() -> 解析 tool_calls -> ToolScheduler 调度 -> 回填结果 -> 重复。
    """

    def __init__(
        self,
        scheduler: ToolScheduler,
        max_iterations: int = MAX_ITERATIONS,
    ) -> None:
        self._scheduler = scheduler
        self._max_iterations = max_iterations

    async def run(
        self,
        llm: BaseLLMService,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        chat_id: str = "",
        on_message: Callable[[dict[str, Any]], None] | None = None,
        source: str = "ruyi",
    ) -> EngineResult:
        """执行 LLM-Tool 循环。

        Parameters
        ----------
        on_message:
            Optional callback invoked with each intermediate message
            (assistant tool_calls and tool responses) as soon as it is
            produced, enabling immediate persistence to disk.
        source:
            输出来源标识 — "ruyi" | "kairos"，传递给 ToolScheduler。
        """
        total_usage = TokenUsage()
        working_messages = list(messages)

        for iteration in range(self._max_iterations):
            response: LLMResponse = await llm.complete(working_messages, tools)

            total_usage.prompt_tokens += response.usage.prompt_tokens
            total_usage.completion_tokens += response.usage.completion_tokens

            if not response.has_tool_calls:
                return EngineResult(
                    text=response.content or "",
                    usage=total_usage,
                    thinking=response.thinking,
                )

            assistant_msg = self._build_assistant_message(response)
            working_messages.append(assistant_msg)
            if on_message:
                on_message(assistant_msg)

            for tc in response.tool_calls:
                logger.info("Tool call [%d]: %s(%s)", iteration + 1, tc.name, tc.arguments[:100])

            tool_msgs = await self._execute_tools(
                response, chat_id, source=source,
            )
            working_messages.extend(tool_msgs)
            for tm in tool_msgs:
                if on_message:
                    on_message(tm)

        logger.warning("Tool loop reached max iterations (%d)", self._max_iterations)
        final = await llm.complete(working_messages, tools=None)
        total_usage.prompt_tokens += final.usage.prompt_tokens
        total_usage.completion_tokens += final.usage.completion_tokens
        return EngineResult(
            text=final.content or "",
            usage=total_usage,
            thinking=final.thinking,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_assistant_message(response: LLMResponse) -> dict[str, Any]:
        raw_tool_calls = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for tc in response.tool_calls
        ]
        msg: dict[str, Any] = {
            "role": "assistant",
            "content": response.content,
            "tool_calls": raw_tool_calls,
        }
        if response.thinking:
            msg["reasoning_content"] = response.thinking
        return msg

    async def _execute_tools(
        self,
        response: LLMResponse,
        chat_id: str,
        source: str = "ruyi",
    ) -> list[dict[str, Any]]:
        raw_tool_calls = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for tc in response.tool_calls
        ]

        results = await self._scheduler.schedule_batch(
            raw_tool_calls,
            chat_id=chat_id,
            source=source,
            assistant_content=response.content or "",
        )

        tool_msgs: list[dict[str, Any]] = []
        for sr in results:
            if sr.success:
                content = sr.result_string
            elif sr.status == ToolCallStatus.CANCELLED:
                content = json.dumps(
                    {"status": "cancelled", "message": sr.error or "工具执行被取消"},
                    ensure_ascii=False,
                )
            else:
                content = json.dumps(
                    {"status": "error", "message": sr.error or "工具执行出错"},
                    ensure_ascii=False,
                )

            tool_msgs.append({
                "role": "tool",
                "tool_call_id": sr.call_id,
                "content": content,
            })

        return tool_msgs
