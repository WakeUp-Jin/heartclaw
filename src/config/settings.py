from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)}")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config.json"
_DEFAULT_ENV_PATH = _PROJECT_ROOT / ".env"


def _load_dotenv(env_path: Path) -> None:
    """将 .env 文件中的键值对注入到 os.environ（不覆盖已有值）。"""
    if not env_path.is_file():
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            os.environ.setdefault(key, value)


def _resolve_env_vars(obj: Any) -> Any:
    """递归替换 JSON 值中的 ${VAR} 占位符。"""
    if isinstance(obj, str):
        return _ENV_VAR_PATTERN.sub(
            lambda m: os.environ.get(m.group(1), ""),
            obj,
        )
    if isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_vars(item) for item in obj]
    return obj


@dataclass
class LLMModelConfig:
    provider: str = ""
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096


@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0


@dataclass
class LLMConfig:
    models: dict[str, LLMModelConfig] = field(default_factory=dict)
    retry: RetryConfig = field(default_factory=RetryConfig)


@dataclass
class FeishuConfig:
    app_id: str = ""
    app_secret: str = ""
    verification_token: str = ""
    encrypt_key: str = ""
    memory_folder_name: str = "PineClaw"


@dataclass
class ChatConfig:
    history_dir: str = "./data/chat_history"
    max_token_estimate: int = 60000
    compress_keep_ratio: float = 0.3


@dataclass
class AppSection:
    log_level: str = "INFO"
    sqlite_db_path: str = "./data/pineclaw.db"


@dataclass
class AppConfig:
    """项目全局配置单例。

    通过 config.json + .env 环境变量加载，提供类型安全的属性访问。
    """

    app: AppSection = field(default_factory=AppSection)
    feishu: FeishuConfig = field(default_factory=FeishuConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    chat: ChatConfig = field(default_factory=ChatConfig)

    # ---- 便捷属性（向后兼容旧 settings 用法）----

    @property
    def log_level(self) -> str:
        return self.app.log_level

    @property
    def sqlite_db_path(self) -> str:
        return self.app.sqlite_db_path

    @property
    def feishu_app_id(self) -> str:
        return self.feishu.app_id

    @property
    def feishu_app_secret(self) -> str:
        return self.feishu.app_secret

    @property
    def feishu_verification_token(self) -> str:
        return self.feishu.verification_token

    @property
    def feishu_encrypt_key(self) -> str:
        return self.feishu.encrypt_key

    @property
    def feishu_memory_folder_name(self) -> str:
        return self.feishu.memory_folder_name

    @property
    def chat_history_dir(self) -> str:
        return self.chat.history_dir

    @property
    def chat_max_token_estimate(self) -> int:
        return self.chat.max_token_estimate

    @property
    def chat_compress_keep_ratio(self) -> float:
        return self.chat.compress_keep_ratio

    def get_llm_model_config(self, tier: str) -> LLMModelConfig:
        """按 ModelTier 名称获取对应的 LLM 模型配置。"""
        cfg = self.llm.models.get(tier)
        if cfg is None:
            raise KeyError(
                f"LLM model tier '{tier}' not found. "
                f"Available: {list(self.llm.models.keys())}"
            )
        return cfg


def _build_config(raw: dict[str, Any]) -> AppConfig:
    """从解析后的 dict 构造 AppConfig 实例。"""
    app_raw = raw.get("app", {})
    feishu_raw = raw.get("feishu", {})
    llm_raw = raw.get("llm", {})
    chat_raw = raw.get("chat", {})

    models: dict[str, LLMModelConfig] = {}
    for tier_name, tier_raw in llm_raw.get("models", {}).items():
        models[tier_name] = LLMModelConfig(**tier_raw)

    retry_raw = llm_raw.get("retry", {})

    return AppConfig(
        app=AppSection(**app_raw),
        feishu=FeishuConfig(**feishu_raw),
        llm=LLMConfig(
            models=models,
            retry=RetryConfig(**retry_raw),
        ),
        chat=ChatConfig(**chat_raw),
    )


def load_config(
    config_path: Path | str | None = None,
    env_path: Path | str | None = None,
) -> AppConfig:
    """加载配置文件并返回 AppConfig 实例。

    1. 先加载 .env 到环境变量
    2. 读取 config.json
    3. 递归替换 ${VAR} 占位符
    4. 构造 AppConfig dataclass
    """
    env_path = Path(env_path) if env_path else _DEFAULT_ENV_PATH
    config_path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH

    _load_dotenv(env_path)

    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        raw = json.load(f)

    resolved = _resolve_env_vars(raw)
    return _build_config(resolved)


# 全局单例 —— import 时即加载
settings = load_config()
