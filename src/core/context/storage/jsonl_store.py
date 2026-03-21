"""JSONL-based context storage implementation.

Refactored from the original ``ChatStore``.  File layout::

    data/chat_history/
        session_20260311_143022.jsonl            <- all messages, append-only
        session_20260311_143022.checkpoint.json  <- compression state (if any)
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from core.context.storage.base import IContextStorage
from utils import logger


class JsonlContextStorage(IContextStorage):
    """Append-only JSONL persistence with checkpoint support."""

    def __init__(self, history_dir: str) -> None:
        self._dir = Path(history_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._session_file: Path = self._find_or_create_session()

    # ------------------------------------------------------------------
    # IContextStorage implementation
    # ------------------------------------------------------------------

    def append(self, message: dict[str, Any]) -> None:
        try:
            with open(self._session_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(message, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error("Failed to append message: %s", e)

    def load_all(self) -> list[dict[str, Any]]:
        return self._read_jsonl(self._session_file)

    def load_from_line(self, line_number: int) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        try:
            with open(self._session_file, "r", encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i >= line_number:
                        line = line.strip()
                        if line:
                            messages.append(json.loads(line))
        except Exception as e:
            logger.error("Failed to load from line %d: %s", line_number, e)
        return messages

    def count_lines(self) -> int:
        try:
            with open(self._session_file, "r", encoding="utf-8") as f:
                return sum(1 for line in f if line.strip())
        except Exception:
            return 0

    def save_checkpoint(self, summary: str, checkpoint_line: int) -> None:
        data = {
            "summary": summary,
            "checkpoint_line": checkpoint_line,
            "created_at": datetime.now().isoformat(),
        }
        try:
            with open(self._checkpoint_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("Checkpoint saved at line %d", checkpoint_line)
        except Exception as e:
            logger.error("Failed to save checkpoint: %s", e)

    def load_checkpoint(self) -> dict[str, Any] | None:
        cp_path = self._checkpoint_path()
        if not cp_path.exists():
            return None
        try:
            with open(cp_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to load checkpoint: %s", e)
            return None

    def new_session(self) -> None:
        old = self._session_file
        self._session_file = self._create_session_file()
        logger.info("New session created. Old: %s, New: %s", old.name, self._session_file.name)

    # ------------------------------------------------------------------
    # Extra properties
    # ------------------------------------------------------------------

    @property
    def session_file(self) -> Path:
        return self._session_file

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_or_create_session(self) -> Path:
        jsonl_files = sorted(self._dir.glob("session_*.jsonl"), reverse=True)
        session_files = [f for f in jsonl_files if not f.name.endswith(".checkpoint.json")]
        if session_files:
            logger.info("Loaded existing session: %s", session_files[0].name)
            return session_files[0]
        return self._create_session_file()

    def _create_session_file(self) -> Path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self._dir / f"session_{ts}.jsonl"
        path.touch()
        logger.info("Created session file: %s", path.name)
        return path

    def _checkpoint_path(self) -> Path:
        return self._session_file.with_suffix(".checkpoint.json")

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        messages.append(json.loads(line))
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error("Failed to read %s: %s", path, e)
        return messages
