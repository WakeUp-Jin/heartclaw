from __future__ import annotations

import logging
import sys
import os
from pathlib import Path

_UVICORN_DEFAULT_FORMAT = "[%(asctime)s] %(levelprefix)s %(name)s - %(message)s"
_UVICORN_ACCESS_FORMAT = (
    '[%(asctime)s] %(levelprefix)s %(name)s - %(client_addr)s - "%(request_line)s" %(status_code)s'
)

_ROOT_LOGGER_NAME = "heartclaw"
_LOG_FORMAT = "[%(asctime)s] %(levelname)s %(name)s - %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_initialized = False


def _get_log_level() -> int:
    """从环境变量获取日志级别（避免在 logger 初始化时循环依赖 config）。"""
    level_str = os.environ.get("LOG_LEVEL", "INFO").upper()
    return getattr(logging, level_str, logging.INFO)


def _get_log_file() -> str | None:
    log_file = os.environ.get("HEARTCLAW_LOG_FILE", "").strip()
    return log_file or None


def _ensure_log_dir(log_file: str | None) -> None:
    if not log_file:
        return
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)


def _ensure_root_logger() -> None:
    """确保根 logger 只初始化一次。"""
    global _initialized
    if _initialized:
        return

    root = logging.getLogger(_ROOT_LOGGER_NAME)
    root.setLevel(_get_log_level())

    if not root.handlers:
        formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

        log_file = _get_log_file()
        if log_file:
            _ensure_log_dir(log_file)
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)

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


def get_uvicorn_log_config(level: str) -> dict:
    """构建 uvicorn 日志配置，使其同时输出到 stdout 和日志文件。"""
    log_level = level.upper()
    handlers: dict[str, dict] = {
        "default": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "default",
        },
        "access": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "access",
        },
    }

    default_handler_names = ["default"]
    access_handler_names = ["access"]

    log_file = _get_log_file()
    if log_file:
        _ensure_log_dir(log_file)
        handlers["file"] = {
            "class": "logging.FileHandler",
            "filename": log_file,
            "encoding": "utf-8",
            "formatter": "default",
        }
        handlers["access_file"] = {
            "class": "logging.FileHandler",
            "filename": log_file,
            "encoding": "utf-8",
            "formatter": "access",
        }
        default_handler_names.append("file")
        access_handler_names.append("access_file")

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": _UVICORN_DEFAULT_FORMAT,
                "datefmt": _DATE_FORMAT,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": _UVICORN_ACCESS_FORMAT,
                "datefmt": _DATE_FORMAT,
            },
        },
        "handlers": handlers,
        "loggers": {
            "uvicorn": {
                "handlers": default_handler_names,
                "level": log_level,
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": default_handler_names,
                "level": log_level,
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": access_handler_names,
                "level": log_level,
                "propagate": False,
            },
        },
    }


# 默认 logger 实例，保持向后兼容
logger = get_logger()
