"""Atomic text writing helper used by file tools."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from utils.logger import get_logger

logger = get_logger("tool.file_write_atomic")


def _resolve_target_path(path: Path) -> Path:
    """Keep symlink inode while writing to its target."""
    try:
        if path.is_symlink():
            return path.resolve(strict=True)
    except OSError:
        logger.warning("Failed to resolve symlink target for %s", path, exc_info=True)
    return path


def write_text_atomic(path: str, content: str, encoding: str = "utf-8") -> None:
    """Write text atomically with fallback and best-effort permission preserve."""
    target_input = Path(path)
    target_path = _resolve_target_path(target_input)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    original_mode: int | None = None
    try:
        original_mode = target_path.stat().st_mode
    except FileNotFoundError:
        original_mode = None
    except OSError:
        logger.warning("Failed to read mode for %s", target_path, exc_info=True)

    tmp_path: Path | None = None
    try:
        fd, raw_tmp_path = tempfile.mkstemp(
            prefix=f".{target_path.name}.tmp.",
            dir=str(target_path.parent),
        )
        tmp_path = Path(raw_tmp_path)
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        if original_mode is not None:
            os.chmod(tmp_path, original_mode)

        os.replace(tmp_path, target_path)
        tmp_path = None
    except OSError as atomic_err:
        logger.warning(
            "Atomic write failed for %s, falling back to direct write: %s",
            target_path,
            atomic_err,
        )
        # Fallback keeps availability in case atomic path fails on filesystem edge-cases.
        with open(target_path, "w", encoding=encoding, newline="") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                logger.warning("Failed to cleanup temp file %s", tmp_path, exc_info=True)
