"""Abstract storage interface for context persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class IContextStorage(ABC):
    """Pure I/O contract for persisting chat messages and compression state."""

    @abstractmethod
    def append(self, message: dict[str, Any]) -> None:
        """Append a single message to the backing store."""
        ...

    @abstractmethod
    def load_all(self) -> list[dict[str, Any]]:
        """Load every message from the current session."""
        ...

    @abstractmethod
    def load_from_line(self, line_number: int) -> list[dict[str, Any]]:
        """Load messages starting from *line_number* (0-based)."""
        ...

    @abstractmethod
    def count_lines(self) -> int:
        """Return the total number of stored messages."""
        ...

    @abstractmethod
    def save_checkpoint(self, summary: str, checkpoint_line: int) -> None:
        """Persist compression checkpoint state."""
        ...

    @abstractmethod
    def load_checkpoint(self) -> dict[str, Any] | None:
        """Load checkpoint or return ``None`` if no checkpoint exists."""
        ...

    @abstractmethod
    def new_session(self) -> None:
        """Start a fresh session.  Old data should be preserved on disk."""
        ...
