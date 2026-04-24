"""Base storage abstractions for local file persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from utils.logger import logger


class IStorage:
    """Base class for local file storage backends.

    Provides common file I/O primitives (read, write, append, delete, list)
    scoped to a dedicated directory that is auto-created on init.
    """

    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    def exists(self, filename: str) -> bool:
        return (self._base_dir / filename).exists()

    def read_text(self, filename: str) -> str:
        path = self._base_dir / filename
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""
        except Exception as e:
            logger.error("Failed to read %s: %s", path, e)
            return ""

    def write_text(self, filename: str, content: str) -> None:
        path = self._base_dir / filename
        try:
            path.write_text(content, encoding="utf-8")
        except Exception as e:
            logger.error("Failed to write %s: %s", path, e)

    def append_text(self, filename: str, content: str) -> None:
        path = self._base_dir / filename
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            logger.error("Failed to append to %s: %s", path, e)

    def delete(self, filename: str) -> bool:
        path = self._base_dir / filename
        try:
            path.unlink(missing_ok=True)
            return True
        except Exception as e:
            logger.error("Failed to delete %s: %s", path, e)
            return False

    def list_files(self, pattern: str = "*") -> list[Path]:
        return sorted(self._base_dir.glob(pattern))


class IContextStorage(ABC):
    """Minimal I/O contract for persisting context items.

    Implemented by ``ShortMemoryStore``; consumed by ``ShortTermMemoryContext``.
    """

    @abstractmethod
    def append(self, message: dict[str, Any]) -> None:
        """Append a single serialised ContextItem dict."""
        ...
