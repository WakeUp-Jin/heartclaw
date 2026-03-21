from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from core.llm.types import LLMConfig, LLMResponse, TokenUsage, ToolCall
from core.llm.services.base import BaseLLMService
from utils.logger import get_logger

logger = get_logger("llm.kimi")


class KimiService(BaseLLMService):
    """Moonshot / Kimi 服务实现。

    兼容 OpenAI SDK，默认 base_url: https://api.moonshot.cn/v1
    """

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self._client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )

    async def _do_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        params: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
        }

        if tools:
            params["tools"] = tools
            params["tool_choice"] = "auto"

        logger.debug(
            "Kimi request: model=%s, messages=%d",
            self.config.model,
            len(messages),
        )

        resp = await self._client.chat.completions.create(**params)

        choice = resp.choices[0]
        message = choice.message

        tool_calls: list[ToolCall] = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=tc.function.arguments,
                    )
                )

        usage = TokenUsage()
        if resp.usage:
            usage = TokenUsage(
                prompt_tokens=resp.usage.prompt_tokens,
                completion_tokens=resp.usage.completion_tokens,
            )

        finish_reason = choice.finish_reason or "stop"

        logger.debug(
            "Kimi response: content_len=%s, tool_calls=%d, tokens=%d, finish=%s",
            len(message.content) if message.content else 0,
            len(tool_calls),
            usage.total_tokens,
            finish_reason,
        )

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=finish_reason,
        )
