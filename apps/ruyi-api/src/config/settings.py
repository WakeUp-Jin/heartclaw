from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.llm.types import TokenUsage

_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)}")

def _find_project_root() -> Path:
    """Find the repository root that owns project-level config files."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "config.json").is_file() or (parent / ".env").is_file():
            return parent
    return current.parent.parent.parent


_PROJECT_ROOT = _find_project_root()
_DEFAULT_ENV_PATH = _PROJECT_ROOT / ".env"


# ------------------------------------------------------------------
# .heartclaw home directory
# ------------------------------------------------------------------

def get_heartclaw_home() -> Path:
    """Return the .heartclaw directory path.

    Priority: $HEARTCLAW_HOME env var > ~/.heartclaw
    """
    env = os.environ.get("HEARTCLAW_HOME")
    if env:
        return Path(env)
    return Path.home() / ".heartclaw"


_DEFAULT_CONFIG_TEMPLATE: dict[str, Any] = {
    "app": {
        "log_level": "INFO",
    },
    "models": {
        "high": {
            "id": "kimi-k2.5",
            "name": "Kimi K2.5",
            "provider": "kimi",
            "api_key": "${KIMI_API_KEY}",
            "base_url": "https://api.moonshot.cn/v1",
            "reasoning": False,
            "context_window": 256000,
            "max_tokens": 16000,
            "temperature": 1.0,
            "cost": {"input_cached": 0.70, "input": 4.00, "output": 21.00},
        },
        "medium": {
            "id": "kimi-k2.5",
            "name": "Kimi K2.5 (medium)",
            "provider": "kimi",
            "api_key": "${KIMI_API_KEY}",
            "base_url": "https://api.moonshot.cn/v1",
            "reasoning": False,
            "context_window": 256000,
            "max_tokens": 16000,
            "temperature": 0.7,
            "cost": {"input_cached": 0.70, "input": 4.00, "output": 21.00},
        },
        "low": {
            "id": "doubao-seed-2.0-lite",
            "name": "Doubao Seed 2.0 Lite",
            "provider": "volcengine",
            "api_key": "${VOLCENGINE_API_KEY}",
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "reasoning": False,
            "context_window": 256000,
            "max_tokens": 128000,
            "temperature": 0.7,
            "cost": {"input_cached": 0.0, "input": 0.3, "output": 0.6},
        },
    },
    "memory": {
        "short_term": {
            "compression_threshold": 0.85,
            "compress_keep_ratio": 0.3,
            "initial_load_ratio": 0.60,
        },
        "long_term": {
            "update_schedule": "23:30",
            "max_file_size_tokens": 3000,
            "enable_diff_check": True,
        },
    },
    "retry": {
        "max_retries": 3,
        "base_delay": 1.0,
        "max_delay": 30.0,
    },
    "feishu": {
        "app_id": "${FEISHU_APP_ID}",
        "app_secret": "${FEISHU_APP_SECRET}",
        "verification_token": "${FEISHU_VERIFICATION_TOKEN}",
        "encrypt_key": "${FEISHU_ENCRYPT_KEY}",
    },
    "tiangong": {
        "agent_type": "codex",
        "poll_interval": 900,
        "workspace_dir": "/workspace",
        "api_key": "${OPENAI_API_KEY}",
        "forge_plan_schedule": "23:00",
    },
    "kairos": {
        "enabled": True,
        "default_sleep_seconds": 300,
        "max_sleep_seconds": 3600,
        "min_sleep_seconds": 30,
    },
}


def ensure_heartclaw_dirs() -> Path:
    """Create the ~/.heartclaw directory tree if it does not exist.

    Returns the heartclaw home path.  Safe to call multiple times.
    """
    home = get_heartclaw_home()

    dirs = [
        home,
        home / "skills",
        home / "skills" / "memory",
        home / "skills" / "memory" / "long_term",
        home / "skills" / "memory" / "short_term",
        home / "skills" / "memory" / "update_logs",
        home / "tiangong",
        home / "tiangong" / "orders",
        home / "tiangong" / "orders" / "pending",
        home / "tiangong" / "orders" / "processing",
        home / "tiangong" / "orders" / "done",
        home / "tiangong" / "orders" / "review",
        home / "tiangong" / "codex",
        home / "skills" / "memory" / "kairos",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    config_path = home / "config.json"
    if not config_path.is_file():
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(_DEFAULT_CONFIG_TEMPLATE, f, ensure_ascii=False, indent=2)
            f.write("\n")

    return home


# ------------------------------------------------------------------
# Env helpers
# ------------------------------------------------------------------

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


# ------------------------------------------------------------------
# Dataclasses
# ------------------------------------------------------------------

@dataclass
class CostConfig:
    """Price per million tokens in CNY (元/M tokens).

    Three dimensions matching LLM provider pricing:
    - input_cached: input price when prompt cache hits
    - input: input price when prompt cache misses
    - output: output price
    """
    input_cached: float = 0.0
    input: float = 0.0
    output: float = 0.0


@dataclass
class ModelConfig:
    """A single LLM model definition."""
    id: str = ""
    name: str = ""
    provider: str = ""
    api_key: str = ""
    base_url: str = ""
    reasoning: bool = False
    context_window: int = 128000
    max_tokens: int = 4096
    temperature: float = 0.7
    cost: CostConfig = field(default_factory=CostConfig)

    def calc_cost(self, usage: TokenUsage) -> float:
        """Calculate cost in CNY from a TokenUsage.

        Formula: (cached * input_cached + uncached * input + completion * output) / 1M
        """
        uncached_input = usage.prompt_tokens - usage.cached_tokens
        return (
            usage.cached_tokens * self.cost.input_cached
            + uncached_input * self.cost.input
            + usage.completion_tokens * self.cost.output
        ) / 1_000_000


@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0


@dataclass
class ShortTermMemoryConfig:
    compression_threshold: float = 0.85
    compress_keep_ratio: float = 0.3
    initial_load_ratio: float = 0.60


@dataclass
class LongTermMemoryConfig:
    update_schedule: str = "23:30"
    max_file_size_tokens: int = 3000
    enable_diff_check: bool = True


@dataclass
class MemoryConfig:
    short_term: ShortTermMemoryConfig = field(default_factory=ShortTermMemoryConfig)
    long_term: LongTermMemoryConfig = field(default_factory=LongTermMemoryConfig)


@dataclass
class FeishuConfig:
    app_id: str = ""
    app_secret: str = ""
    verification_token: str = ""
    encrypt_key: str = ""


@dataclass
class TianGongConfig:
    """天工模块配置。"""
    agent_type: str = "codex"
    poll_interval: int = 900
    workspace_dir: str = "/workspace"
    api_key: str = ""
    forge_plan_schedule: str = "23:00"
    max_forge_seconds: int = 3600
    enable_forge_timeout: bool = True
    cancel_check_interval_seconds: int = 10
    agent_log_tail_lines: int = 80


@dataclass
class KairosConfig:
    """KAIROS 自治模式配置。"""
    enabled: bool = True
    default_sleep_seconds: int = 300
    max_sleep_seconds: int = 3600
    min_sleep_seconds: int = 30


@dataclass
class AppSection:
    log_level: str = "INFO"
    channel_mode: str = ""


@dataclass
class AppConfig:
    """Global configuration loaded from ~/.heartclaw/config.json + .env."""

    app: AppSection = field(default_factory=AppSection)
    models: dict[str, ModelConfig] = field(default_factory=dict)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    feishu: FeishuConfig = field(default_factory=FeishuConfig)
    tiangong: TianGongConfig = field(default_factory=TianGongConfig)
    kairos: KairosConfig = field(default_factory=KairosConfig)

    # ---- convenience properties ----

    @property
    def log_level(self) -> str:
        return self.app.log_level

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
    def short_term_dir(self) -> Path:
        return get_heartclaw_home() / "skills" / "memory" / "short_term"

    @property
    def long_term_dir(self) -> Path:
        return get_heartclaw_home() / "skills" / "memory" / "long_term"

    @property
    def update_log_dir(self) -> Path:
        return get_heartclaw_home() / "skills" / "memory" / "update_logs"

    @property
    def memory_update_schedule(self) -> str:
        return self.memory.long_term.update_schedule

    @property
    def initial_load_ratio(self) -> float:
        return self.memory.short_term.initial_load_ratio

    @property
    def channel_mode(self) -> str:
        return self.app.channel_mode

    @property
    def kairos_memory_dir(self) -> Path:
        return get_heartclaw_home() / "skills" / "memory" / "kairos"

    @property
    def compression_threshold(self) -> float:
        return self.memory.short_term.compression_threshold

    @property
    def compress_keep_ratio(self) -> float:
        return self.memory.short_term.compress_keep_ratio

    def get_model_config(self, tier: str) -> ModelConfig:
        """Get ModelConfig by tier name (high/medium/low)."""
        cfg = self.models.get(tier)
        if cfg is None:
            raise KeyError(
                f"Model tier '{tier}' not found. "
                f"Available: {list(self.models.keys())}"
            )
        return cfg


# ------------------------------------------------------------------
# Config builder
# ------------------------------------------------------------------

def _build_config(raw: dict[str, Any]) -> AppConfig:
    """Construct AppConfig from a resolved dict."""
    app_raw = raw.get("app", {})
    feishu_raw = raw.get("feishu", {})
    retry_raw = raw.get("retry", {})
    memory_raw = raw.get("memory", {})
    st_raw = memory_raw.get("short_term", {})
    lt_raw = memory_raw.get("long_term", {})
    tiangong_raw = raw.get("tiangong", {})
    kairos_raw = raw.get("kairos", {})

    models: dict[str, ModelConfig] = {}
    for tier_name, tier_raw in raw.get("models", {}).items():
        cost_raw = tier_raw.pop("cost", {})
        cost = CostConfig(**cost_raw) if isinstance(cost_raw, dict) else CostConfig()
        models[tier_name] = ModelConfig(**tier_raw, cost=cost)

    return AppConfig(
        app=AppSection(**app_raw),
        models=models,
        memory=MemoryConfig(
            short_term=ShortTermMemoryConfig(**st_raw),
            long_term=LongTermMemoryConfig(**lt_raw),
        ),
        retry=RetryConfig(**retry_raw),
        feishu=FeishuConfig(**feishu_raw),
        tiangong=TianGongConfig(**tiangong_raw),
        kairos=KairosConfig(**kairos_raw),
    )


def load_config(
    config_path: Path | str | None = None,
    env_path: Path | str | None = None,
) -> AppConfig:
    """Load config from ~/.heartclaw/config.json + .env.

    1. Ensure ~/.heartclaw/ directory tree exists (create if missing)
    2. Load .env into environment
    3. Read config.json and resolve ${VAR} placeholders
    4. Build typed AppConfig
    5. Override channel_mode from $HEARTCLAW_CHANNEL_MODE if set
    """
    home = ensure_heartclaw_dirs()

    env_path = Path(env_path) if env_path else _DEFAULT_ENV_PATH
    config_path = Path(config_path) if config_path else (home / "config.json")

    _load_dotenv(env_path)

    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        raw = json.load(f)

    resolved = _resolve_env_vars(raw)
    cfg = _build_config(resolved)

    channel_env = os.environ.get("HEARTCLAW_CHANNEL_MODE", "").strip().lower()
    if channel_env:
        cfg.app.channel_mode = channel_env
    elif not cfg.app.channel_mode:
        cfg.app.channel_mode = "none"

    return cfg


settings = load_config()
