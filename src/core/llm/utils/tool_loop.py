from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from core.llm.types import LLMResponse, TokenUsage
from utils import logger

if TYPE_CHECKING:
    from core.llm.services.base import BaseLLMService
    from core.tool.manager import ToolManager

MAX_ITERATIONS = 10


async def execute_tool_loop(
    llm: BaseLLMService,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_manager: ToolManager,
    max_iterations: int = MAX_ITERATIONS,
) -> tuple[str, TokenUsage, list[dict[str, Any]]]:
    """Run the LLM -> tool_call -> execute -> repeat loop.

    Returns (final_text, aggregated_usage, intermediate_messages).
    ``intermediate_messages`` contains all assistant (with tool_calls) and
    tool-result messages produced during the loop, in order.
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

        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": response.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in response.tool_calls
            ],
        }
        working_messages.append(assistant_msg)
        intermediate_messages.append(assistant_msg)

        for tc in response.tool_calls:
            logger.info("Tool call [%d]: %s(%s)", iteration + 1, tc.name, tc.arguments[:100])

            try:
                result = await tool_manager.execute(tc.name, tc.arguments)
            except Exception as e:
                logger.error("Tool %s failed: %s", tc.name, e)
                result = json.dumps({"error": str(e)})

            tool_msg: dict[str, Any] = {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            }
            working_messages.append(tool_msg)
            intermediate_messages.append(tool_msg)

    logger.warning("Tool loop reached max iterations (%d)", max_iterations)
    final = await llm.complete(working_messages, tools=None)
    total_usage.prompt_tokens += final.usage.prompt_tokens
    total_usage.completion_tokens += final.usage.completion_tokens
    return final.content or "", total_usage, intermediate_messages
