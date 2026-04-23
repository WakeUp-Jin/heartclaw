"""Unified local file storage layer.

Provides three storage backends:
- ``LocalMemoryStore`` -- Markdown-based long-term memory

And the abstract contracts:
- ``IStorage``          -- base class with file I/O primitives
- ``IContextStorage``   -- interface for conversation persistence
"""

from storage.base import IStorage, IContextStorage
from storage.memory_store import LocalMemoryStore

__all__ = [
    "IStorage",
    "IContextStorage",
    "LocalMemoryStore",
]
