from __future__ import annotations

import logging
import sys
import os

_ROOT_LOGGER_NAME = "heartclaw"
_LOG_FORMAT = "[%(asctime)s] %(levelname)s %(name)s - %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_initialized = False


def _get_log_level() -> int:
    """从环境变量获取日志级别（避免在 logger 初始化时循环依赖 config）。"""
    level_str = os.environ.get("LOG_LEVEL", "INFO").upper()
    return getattr(logging, level_str, logging.INFO)


def _ensure_root_logger() -> None:
    """确保根 logger 只初始化一次。"""
    global _initialized
    if _initialized:
        return

    root = logging.getLogger(_ROOT_LOGGER_NAME)
    root.setLevel(_get_log_level())

    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
        root.addHandler(handler)

    _initialized = True


def get_logger(name: str | None = None) -> logging.Logger:
    """获取模块级 logger。

    - get_logger()          → heartclaw
    - get_logger("llm")     → heartclaw.llm
    - get_logger("llm.kimi") → heartclaw.llm.kimi
    """
    _ensure_root_logger()
    if name:
        return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")
    return logging.getLogger(_ROOT_LOGGER_NAME)


def set_log_level(level: str) -> None:
    """运行时动态调整日志级别。"""
    _ensure_root_logger()
    root = logging.getLogger(_ROOT_LOGGER_NAME)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


# 默认 logger 实例，保持向后兼容
logger = get_logger()
