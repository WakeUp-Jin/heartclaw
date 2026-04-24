from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from typing import Any

from core.llm.types import LLMConfig, LLMResponse
from utils.logger import get_logger

logger = get_logger("llm")


class BaseLLMService(ABC):
    """LLM 服务基类。

    子类只需实现 _do_complete；complete / simple_chat / 重试 由基类统一处理。
    """

    def __init__(self, config: LLMConfig):
        self.config = config

    # ---- 子类必须实现 ----

    @abstractmethod
    async def _do_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse: ...

    # ---- 公开接口 ----

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """带自动重试的补全调用。"""
        return await self._complete_with_retry(messages, tools, **kwargs)

    async def simple_chat(
        self,
        user_input: str,
        system_prompt: str = "",
    ) -> str:
        """简单对话：无工具、单轮。"""
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_input})

        response = await self.complete(messages, tools=None)
        return response.content or ""

    # ---- 重试机制 ----

    async def _complete_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        max_retries = self.config.max_retries
        for attempt in range(max_retries + 1):
            try:
                return await self._do_complete(messages, tools, **kwargs)
            except Exception as exc:
                if not self._is_retryable_error(exc) or attempt == max_retries:
                    raise
                delay = min(
                    1.0 * (2 ** attempt) + random.uniform(0, 1.0),
                    30.0,
                )
                logger.warning(
                    "LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    max_retries,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)

        raise RuntimeError("Max retries exceeded")

    @staticmethod
    def _is_retryable_error(error: Exception) -> bool:
        status = getattr(error, "status_code", None) or getattr(error, "status", None)
        if status is not None:
            if status == 429 or (500 <= status < 600):
                return True
            if status in (400, 401, 403):
                return False

        code = getattr(error, "code", None)
        if code in ("ECONNRESET", "ETIMEDOUT"):
            return True

        error_name = type(error).__name__
        if any(
            keyword in error_name
            for keyword in ("Timeout", "Connection", "Network")
        ):
            return True

        return False
