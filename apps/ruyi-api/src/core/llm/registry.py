from __future__ import annotations

import json
from typing import TYPE_CHECKING

from core.llm.types import LLMConfig, ModelTier
from core.llm.factory import create_llm_service
from utils.logger import get_logger

if TYPE_CHECKING:
    from config.settings import AppConfig
    from core.llm.services.base import BaseLLMService

logger = get_logger("llm.registry")


class LLMServiceRegistry:
    """按 ModelTier 管理和缓存 LLM 服务实例。

    - 延迟创建：首次 get_service 时才创建实例
    - 配置感知：配置变更自动重建实例
    - 单例缓存：同一 tier 共享一个服务实例
    """

    def __init__(self, config: AppConfig):
        self._config = config
        self._cache: dict[ModelTier, BaseLLMService] = {}
        self._config_hashes: dict[ModelTier, str] = {}

    def get_service(self, tier: ModelTier) -> BaseLLMService:
        """获取指定层级的服务（带缓存）。"""
        current_hash = self._compute_config_hash(tier)
        if self._config_hashes.get(tier) != current_hash:
            self._invalidate(tier)

        if tier in self._cache:
            return self._cache[tier]

        llm_config = self._build_llm_config(tier)
        service = create_llm_service(llm_config)
        self._cache[tier] = service
        self._config_hashes[tier] = current_hash

        logger.info(
            "LLM service created for tier=%s: provider=%s, model=%s",
            tier.value,
            llm_config.provider,
            llm_config.model,
        )
        return service

    def get_high(self) -> BaseLLMService:
        return self.get_service(ModelTier.HIGH)

    def get_medium(self) -> BaseLLMService:
        return self.get_service(ModelTier.MEDIUM)

    def get_low(self) -> BaseLLMService:
        return self.get_service(ModelTier.LOW)

    def invalidate_all(self) -> None:
        self._cache.clear()
        self._config_hashes.clear()

    def _invalidate(self, tier: ModelTier) -> None:
        self._cache.pop(tier, None)
        self._config_hashes.pop(tier, None)

    def _build_llm_config(self, tier: ModelTier) -> LLMConfig:
        """从 AppConfig 构造 LLMConfig。"""
        model_cfg = self._config.get_model_config(tier.value)
        return LLMConfig(
            provider=model_cfg.provider,
            api_key=model_cfg.api_key,
            base_url=model_cfg.base_url,
            model=model_cfg.id,
            temperature=model_cfg.temperature,
            max_tokens=model_cfg.max_tokens,
            max_retries=self._config.retry.max_retries,
        )

    def _compute_config_hash(self, tier: ModelTier) -> str:
        model_cfg = self._config.get_model_config(tier.value)
        return json.dumps(
            {"provider": model_cfg.provider, "model": model_cfg.id},
            sort_keys=True,
        )
