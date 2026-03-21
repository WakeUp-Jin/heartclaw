"""ExecutionEngine — LLM + Tool 循环的核心执行引擎。

实现 LLM -> tool_calls -> ToolScheduler -> repeat 的主循环，
直到 LLM 返回纯文本或达到最大迭代次数。
"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from core.llm.types import LLMResponse, TokenUsage
from core.tool.types import ToolCallStatus
from utils.logger import get_logger

logger = get_logger("engine")

if TYPE_CHECKING:
    from core.llm.services.base import BaseLLMService
    from core.tool.scheduler import ToolScheduler

MAX_ITERATIONS = 10


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
    ) -> tuple[str, TokenUsage, list[dict[str, Any]]]:
        """执行 LLM-Tool 循环。

        Returns:
            (final_text, aggregated_usage, intermediate_messages)
        """
        total_usage = TokenUsage()
        working_messages = list(messages)
        intermediate: list[dict[str, Any]] = []

        for iteration in range(self._max_iterations):
            response: LLMResponse = await llm.complete(working_messages, tools)

            total_usage.prompt_tokens += response.usage.prompt_tokens
            total_usage.completion_tokens += response.usage.completion_tokens

            if not response.has_tool_calls:
                return response.content or "", total_usage, intermediate

            assistant_msg = self._build_assistant_message(response)
            working_messages.append(assistant_msg)
            intermediate.append(assistant_msg)

            for tc in response.tool_calls:
                logger.info("Tool call [%d]: %s(%s)", iteration + 1, tc.name, tc.arguments[:100])

            tool_msgs = await self._execute_tools(response, chat_id)
            working_messages.extend(tool_msgs)
            intermediate.extend(tool_msgs)

        logger.warning("Tool loop reached max iterations (%d)", self._max_iterations)
        final = await llm.complete(working_messages, tools=None)
        total_usage.prompt_tokens += final.usage.prompt_tokens
        total_usage.completion_tokens += final.usage.completion_tokens
        return final.content or "", total_usage, intermediate

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
        return {
            "role": "assistant",
            "content": response.content,
            "tool_calls": raw_tool_calls,
        }

    async def _execute_tools(
        self,
        response: LLMResponse,
        chat_id: str,
    ) -> list[dict[str, Any]]:
        raw_tool_calls = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for tc in response.tool_calls
        ]

        results = await self._scheduler.schedule_batch(raw_tool_calls, chat_id=chat_id)

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
