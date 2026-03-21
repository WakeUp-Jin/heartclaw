from __future__ import annotations

from core.llm.types import LLMConfig
from core.llm.services.base import BaseLLMService
from core.llm.services.kimi_service import KimiService
from core.llm.services.volcengine_service import VolcEngineService
from core.llm.services.openai_service import OpenAIService
from core.llm.utils.llm_helpers import extract_api_key, get_base_url
from utils.logger import get_logger

logger = get_logger("llm.factory")

_PROVIDERS: dict[str, type[BaseLLMService]] = {
    "kimi": KimiService,
    "volcengine": VolcEngineService,
    "openai": OpenAIService,
    "deepseek": OpenAIService,
}


def create_llm_service(config: LLMConfig) -> BaseLLMService:
    """根据 LLMConfig 创建对应的 LLM 服务实例。

    在创建前自动解析 api_key 和 base_url（通过 llm_helpers）。
    """
    resolved_config = LLMConfig(
        provider=config.provider,
        api_key=extract_api_key(config),
        base_url=get_base_url(config),
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        max_retries=config.max_retries,
    )

    provider = resolved_config.provider.lower()
    service_cls = _PROVIDERS.get(provider)
    if service_cls is None:
        raise ValueError(
            f"Unknown LLM provider: {provider}. "
            f"Available: {list(_PROVIDERS.keys())}"
        )

    logger.info(
        "Creating LLM service: provider=%s, model=%s",
        provider,
        resolved_config.model,
    )

    return service_cls(resolved_config)
