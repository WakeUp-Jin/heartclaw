"""BaseContext generic abstract base class.

Every context module inherits from ``BaseContext[T]`` and implements ``format()``
to produce a ``ContextParts`` instance for the context assembly pipeline.
``ContextParts`` separates system-level text (merged into one system message)
from conversation-level messages (placed in the message list).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from core.context.types import ContextParts

T = TypeVar("T")


class BaseContext(ABC, Generic[T]):
    """Generic base providing standard CRUD operations on stored items."""

    def __init__(self) -> None:
        self._items: list[T] = []

    def add(self, item: T) -> None:
        self._items.append(item)

    def get(self, index: int) -> T | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def get_all(self) -> list[T]:
        return list(self._items)

    def clear(self) -> None:
        self._items.clear()

    def remove_last(self) -> T | None:
        if self._items:
            return self._items.pop()
        return None

    def replace(self, items: list[T]) -> None:
        self._items = list(items)

    def slice(self, start: int, end: int | None = None) -> list[T]:
        return self._items[start:end]

    def count(self) -> int:
        return len(self._items)

    def is_empty(self) -> bool:
        return len(self._items) == 0

    @abstractmethod
    def format(self) -> ContextParts:
        """子类返回 ContextParts，声明内容投递到 system 还是 messages。"""
        ...
