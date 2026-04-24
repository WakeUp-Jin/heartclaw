from __future__ import annotations

from typing import Any

from channels.types import IChannel
from utils.logger import logger

_registry: dict[str, IChannel] = {}


def register_channel(channel: IChannel) -> None:
    _registry[channel.name] = channel
    logger.info("Channel registered: %s", channel.name)


def get_channel(name: str) -> IChannel | None:
    return _registry.get(name)


def get_all_channels() -> dict[str, IChannel]:
    return dict(_registry)
