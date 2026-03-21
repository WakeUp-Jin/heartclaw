from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from core.llm.types import LLMResponse, TokenUsage
from core.tool.types import ToolCallStatus
from utils.logger import get_logger

logger = get_logger("llm.tool_loop")

if TYPE_CHECKING:
    from core.llm.services.base import BaseLLMService
    from core.tool.scheduler import ToolScheduler

MAX_ITERATIONS = 10


async def execute_tool_loop(
    llm: BaseLLMService,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    scheduler: ToolScheduler,
    chat_id: str = "",
    max_iterations: int = MAX_ITERATIONS,
) -> tuple[str, TokenUsage, list[dict[str, Any]]]:
    """LLM -> tool_calls -> ToolScheduler -> repeat 循环。

    Returns (final_text, aggregated_usage, intermediate_messages).
    """
    total_usage = TokenUsage()
    working_messages = list(messages)
    intermediate_messages: list[dict[str, Any]] = []

    for iteration in range(max_iterations):
        response: LLMResponse = await llm.complete(working_messages, tools)

        total_usage.prompt_tokens += response.usage.prompt_tokens
        total_usage.completion_tokens += response.usage.completion_tokens

        if not response.has_tool_calls:
            return response.content or "", total_usage, intermediate_messages

        # 构造 assistant 消息（含 tool_calls）
        raw_tool_calls = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for tc in response.tool_calls
        ]

        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": response.content,
            "tool_calls": raw_tool_calls,
        }
        working_messages.append(assistant_msg)
        intermediate_messages.append(assistant_msg)

        for tc in response.tool_calls:
            logger.info("Tool call [%d]: %s(%s)", iteration + 1, tc.name, tc.arguments[:100])

        # 通过 ToolScheduler 批量调度
        results = await scheduler.schedule_batch(raw_tool_calls, chat_id=chat_id)

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

            tool_msg: dict[str, Any] = {
                "role": "tool",
                "tool_call_id": sr.call_id,
                "content": content,
            }
            working_messages.append(tool_msg)
            intermediate_messages.append(tool_msg)

    logger.warning("Tool loop reached max iterations (%d)", max_iterations)
    final = await llm.complete(working_messages, tools=None)
    total_usage.prompt_tokens += final.usage.prompt_tokens
    total_usage.completion_tokens += final.usage.completion_tokens
    return final.content or "", total_usage, intermediate_messages
