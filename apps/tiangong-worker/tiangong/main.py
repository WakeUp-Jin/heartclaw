"""天工调度器入口。

从共享卷读取 config.json 中的 tiangong 配置，启动巡查主循环。
在 Docker 容器中运行: python -m tiangong.main
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path

from tiangong.engine import TianGongEngine

_LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"


def _build_log_handlers() -> list[logging.Handler]:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    log_file = os.environ.get("TIANGONG_LOG_FILE", "").strip()
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    return handlers


logging.basicConfig(
    level=logging.INFO,
    format=_LOG_FORMAT,
    handlers=_build_log_handlers(),
    force=True,
)
logger = logging.getLogger("tiangong.main")

_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)}")

DEFAULT_SHARED_DIR = "/shared"


def _resolve_env_vars(obj):
    """递归替换 JSON 值中的 ${VAR} 占位符。"""
    if isinstance(obj, str):
        return _ENV_VAR_PATTERN.sub(
            lambda m: os.environ.get(m.group(1), ""), obj
        )
    if isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_vars(item) for item in obj]
    return obj


def load_config(shared_dir: str | None = None) -> dict:
    """从共享卷的 config.json 读取天工配置。

    配置统一在 ~/.heartclaw/config.json 中管理，天工只取 "tiangong" 部分。
    API Key 等敏感信息使用 ${VAR} 占位符，运行时从环境变量解析。
    """
    shared = Path(shared_dir or DEFAULT_SHARED_DIR)
    config_path = shared / "config.json"

    if not config_path.is_file():
        logger.warning("config.json not found at %s, using defaults.", config_path)
        return {
            "shared_dir": str(shared),
            "workspace_dir": "/workspace",
            "poll_interval": 900,
            "max_forge_seconds": 3600,
            "enable_forge_timeout": True,
            "cancel_check_interval_seconds": 10,
            "agent_log_tail_lines": 80,
            "agent": {"type": "codex", "workspace_dir": "/workspace"},
        }

    with open(config_path, encoding="utf-8") as f:
        raw = json.load(f)

    resolved = _resolve_env_vars(raw)
    tiangong_cfg = resolved.get("tiangong", {})

    config = {
        "shared_dir": str(shared),
        "workspace_dir": tiangong_cfg.get("workspace_dir", "/workspace"),
        "poll_interval": tiangong_cfg.get("poll_interval", 900),
        "max_forge_seconds": tiangong_cfg.get("max_forge_seconds", 3600),
        "enable_forge_timeout": tiangong_cfg.get("enable_forge_timeout", True),
        "cancel_check_interval_seconds": tiangong_cfg.get(
            "cancel_check_interval_seconds", 10
        ),
        "agent_log_tail_lines": tiangong_cfg.get("agent_log_tail_lines", 80),
        "agent": {
            "type": tiangong_cfg.get("agent_type", "codex"),
            "workspace_dir": tiangong_cfg.get("workspace_dir", "/workspace"),
        },
    }

    logger.info(
        "Config loaded: agent=%s, poll=%ds",
        config["agent"]["type"],
        config["poll_interval"],
    )
    return config


async def main() -> None:
    config = load_config()
    engine = TianGongEngine(config)
    engine.validate_runtime()
    await engine.run()


if __name__ == "__main__":
    asyncio.run(main())
