from __future__ import annotations

from core.llm.types import LLMConfig

NO_KEY_PROVIDERS = frozenset({"ollama", "lmstudio", "aws"})

DEFAULT_BASE_URLS: dict[str, str] = {
    "kimi": "https://api.moonshot.cn/v1",
    "volcengine": "https://ark.cn-beijing.volces.com/api/v3",
    "deepseek": "https://api.deepseek.com",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
}

def extract_api_key(config: LLMConfig) -> str:
    """提取 API Key。

    优先级：
    1. config.api_key（由 AppConfig 解析好）
    2. 无需 API Key 的供应商返回占位符
    """
    provider = config.provider.lower()

    if provider in NO_KEY_PROVIDERS:
        return "not-required"

    if config.api_key:
        return config.api_key

    raise ValueError(
        f'API key not found for provider "{provider}". '
        f"Please configure your API key in config.json or .env"
    )


def get_base_url(config: LLMConfig) -> str:
    """获取供应商的 Base URL。

    优先级：
    1. config.base_url（显式配置）
    2. 硬编码的默认 Base URL
    """
    if config.base_url:
        return config.base_url

    provider = config.provider.lower()
    base_url = DEFAULT_BASE_URLS.get(provider)
    if not base_url:
        raise ValueError(
            f'No base URL found for provider "{provider}". '
            f"Please pass base_url in config."
        )

    return base_url
