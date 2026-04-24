"""Daily-file based short-term memory storage.

File layout::

    ~/.heartclaw/skills/memory/short_term/
        state.json
        2026-03/
            2026-03-29.jsonl          <- today's raw ContextItem dicts
            2026-03-29_001.jsonl      <- created after first /clear
            2026-03-28.jsonl
            week_03-17_to_03-23.summary.md
        2026-02/
            month_2026-02.summary.md
            2026-02-28.jsonl
        year_2025.summary.md

Segment naming: the plain file (no suffix) is the initial segment.
Each /clear creates a new segment with an incrementing suffix (_001, _002, ...).
On load only the latest segment is read; compression reads all segments.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from storage.base import IContextStorage
from utils.logger import logger

_DATE_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_SEGMENT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:_(\d{3}))?\.jsonl$")


class ShortMemoryStore(IContextStorage):
    """Append-only JSONL storage organised into daily files within monthly folders.

    Supports same-day segmentation: /clear creates a new segment file
    (e.g. 2026-04-06_001.jsonl) while leaving the original intact.
    """

    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._today: date = date.today()
        self._active_file: Path = self._find_active_file(self._today)

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(self, message: dict[str, Any]) -> None:
        today = date.today()
        if today != self._today:
            self._today = today
            self._active_file = self._find_active_file(today)

        try:
            with open(self._active_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(message, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error("ShortMemoryStore.append failed: %s", e)

    def rotate_daily(self) -> None:
        """Create a new segment file for today (/clear trigger).

        The previous file is left intact on disk for compression to use later.
        """
        next_seq = self._next_sequence_number(self._today)
        path = self._build_segment_path(self._today, next_seq)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        self._active_file = path
        logger.info("Rotated to new segment: %s", path.name)

    def save_summary(self, path: Path, content: str) -> None:
        """Write a summary file (.summary.md) to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(content, encoding="utf-8")
            logger.info("Summary saved: %s (%d chars)", path.name, len(content))
        except Exception as e:
            logger.error("Failed to save summary %s: %s", path, e)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load_today(self) -> list[dict[str, Any]]:
        return self._read_jsonl(self._active_file)

    def load_daily(self, d: date) -> list[dict[str, Any]]:
        """Load only the **latest** segment for the given date.

        Used by _load_memory(); segments before /clear are treated as
        intentionally forgotten by the user.
        """
        path = self._find_latest_segment(d)
        if path is None:
            return []
        return self._read_jsonl(path)

    def load_daily_all(self, d: date) -> list[dict[str, Any]]:
        """Load **all** segments for the given date (plain + numbered).

        Used by compression — all conversation data for a day should be
        included in week summaries regardless of /clear boundaries.
        """
        result: list[dict[str, Any]] = []
        for path in self.list_daily_segments(d):
            result.extend(self._read_jsonl(path))
        return result

    def count_today_lines(self) -> int:
        try:
            with open(self._active_file, "r", encoding="utf-8") as f:
                return sum(1 for line in f if line.strip())
        except FileNotFoundError:
            return 0
        except Exception:
            return 0

    def read_summary(self, path: Path) -> str:
        """Read a summary file's text content."""
        try:
            return path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error("Failed to read summary %s: %s", path, e)
            return ""

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def get_daily_path(self, d: date) -> Path:
        """Return the plain (no-suffix) daily file path.

        This is the canonical path for the initial segment.
        """
        month_dir = self._base_dir / d.strftime("%Y-%m")
        return month_dir / f"{d.isoformat()}.jsonl"

    def get_month_dir(self, d: date) -> Path:
        return self._base_dir / d.strftime("%Y-%m")

    def list_daily_segments(self, d: date) -> list[Path]:
        """Return all segment files for a given date, sorted by creation order.

        Returns the plain file first (if it exists), then _001, _002, etc.
        """
        month_dir = self.get_month_dir(d)
        if not month_dir.is_dir():
            return []

        prefix = d.isoformat()
        plain = month_dir / f"{prefix}.jsonl"
        segments: list[Path] = []
        if plain.exists():
            segments.append(plain)
        numbered = sorted(month_dir.glob(f"{prefix}_*.jsonl"))
        segments.extend(numbered)
        return segments

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_month_dirs(self) -> list[Path]:
        """All month directories sorted oldest first."""
        dirs = [
            d for d in self._base_dir.iterdir()
            if d.is_dir() and re.match(r"\d{4}-\d{2}$", d.name)
        ]
        return sorted(dirs, key=lambda p: p.name)

    def list_daily_files(self, month_dir: Path) -> list[Path]:
        """All .jsonl files in a month directory, sorted oldest first."""
        return sorted(month_dir.glob("*.jsonl"), key=lambda p: p.name)

    def list_summaries(self, month_dir: Path) -> list[Path]:
        """All .summary.md files in a month directory."""
        return sorted(month_dir.glob("*.summary.md"), key=lambda p: p.name)

    def list_year_summaries(self) -> list[Path]:
        """Year summary files in the base directory."""
        return sorted(self._base_dir.glob("year_*.summary.md"), key=lambda p: p.name)

    def get_all_dates_descending(self) -> list[date]:
        """Return all dates that have .jsonl files, newest first.

        Handles both plain files (2026-04-06.jsonl) and segment files
        (2026-04-06_001.jsonl). Each date appears only once.
        """
        seen: set[date] = set()
        dates: list[date] = []
        for month_dir in reversed(self.list_month_dirs()):
            for f in reversed(self.list_daily_files(month_dir)):
                d = self._extract_date_from_filename(f.name)
                if d is not None and d not in seen:
                    seen.add(d)
                    dates.append(d)
        return dates

    def is_covered_by_summary(self, d: date, summaries: list[Path]) -> bool:
        """Check if a date falls within any week or month summary's range."""
        for s in summaries:
            name = s.name.replace(".summary.md", "")

            if name.startswith("week_"):
                parts = name.replace("week_", "").split("_to_")
                if len(parts) == 2:
                    try:
                        year = d.year
                        start = date(year, int(parts[0][:2]), int(parts[0][3:]))
                        end = date(year, int(parts[1][:2]), int(parts[1][3:]))
                        if start <= d <= end:
                            return True
                    except (ValueError, IndexError):
                        continue

            elif name.startswith("month_"):
                month_str = name.replace("month_", "")
                if d.strftime("%Y-%m") == month_str:
                    return True

        return False

    def find_covering_summary(self, d: date, summaries: list[Path]) -> Path | None:
        """Return the summary file that covers this date, or None."""
        for s in summaries:
            name = s.name.replace(".summary.md", "")

            if name.startswith("week_"):
                parts = name.replace("week_", "").split("_to_")
                if len(parts) == 2:
                    try:
                        year = d.year
                        start = date(year, int(parts[0][:2]), int(parts[0][3:]))
                        end = date(year, int(parts[1][:2]), int(parts[1][3:]))
                        if start <= d <= end:
                            return s
                    except (ValueError, IndexError):
                        continue

            elif name.startswith("month_"):
                month_str = name.replace("month_", "")
                if d.strftime("%Y-%m") == month_str:
                    return s

        return None

    # ------------------------------------------------------------------
    # Internal: segment management
    # ------------------------------------------------------------------

    def _find_active_file(self, d: date) -> Path:
        """Find (or create) the file to write to for the given date.

        Priority: latest numbered segment > plain file > create plain file.
        """
        month_dir = self.get_month_dir(d)
        prefix = d.isoformat()

        if month_dir.is_dir():
            numbered = sorted(month_dir.glob(f"{prefix}_*.jsonl"))
            if numbered:
                return numbered[-1]

        plain = month_dir / f"{prefix}.jsonl"
        if plain.exists():
            return plain

        month_dir.mkdir(parents=True, exist_ok=True)
        plain.touch()
        logger.debug("Created daily file: %s", plain.name)
        return plain

    def _find_latest_segment(self, d: date) -> Path | None:
        """Return the latest segment for a date without creating anything."""
        month_dir = self.get_month_dir(d)
        if not month_dir.is_dir():
            return None

        prefix = d.isoformat()
        numbered = sorted(month_dir.glob(f"{prefix}_*.jsonl"))
        if numbered:
            return numbered[-1]

        plain = month_dir / f"{prefix}.jsonl"
        if plain.exists():
            return plain
        return None

    def _next_sequence_number(self, d: date) -> int:
        """Determine the next segment sequence number for a date."""
        month_dir = self.get_month_dir(d)
        if not month_dir.is_dir():
            return 1

        prefix = d.isoformat()
        max_seq = 0
        for f in month_dir.glob(f"{prefix}_*.jsonl"):
            m = _SEGMENT_RE.match(f.name)
            if m and m.group(2):
                max_seq = max(max_seq, int(m.group(2)))
        return max_seq + 1

    def _build_segment_path(self, d: date, seq: int) -> Path:
        month_dir = self.get_month_dir(d)
        return month_dir / f"{d.isoformat()}_{seq:03d}.jsonl"

    @staticmethod
    def _extract_date_from_filename(name: str) -> date | None:
        """Extract the date portion from a daily/segment filename.

        Handles: '2026-04-06.jsonl' and '2026-04-06_001.jsonl'.
        """
        m = _SEGMENT_RE.match(name)
        if m:
            try:
                return date.fromisoformat(m.group(1))
            except ValueError:
                return None
        return None

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
            logger.error("_read_jsonl failed on %s: %s", path, e)
        return messages
