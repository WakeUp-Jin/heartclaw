"""Daily-file based short-term memory storage.

File layout::

    ~/.heartclaw/skills/memory/short_term/
        state.json
        2026-03/
            2026-03-29.jsonl          <- today's raw ContextItem dicts
            2026-03-28.jsonl
            week_03-17_to_03-23.summary.md
        2026-02/
            month_2026-02.summary.md
            2026-02-28.jsonl
        year_2025.summary.md
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from storage.base import IContextStorage
from utils.logger import logger


class ShortMemoryStore(IContextStorage):
    """Append-only JSONL storage organised into daily files within monthly folders."""

    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._today: date = date.today()
        self._ensure_today_file()

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
            self._ensure_today_file()

        path = self.get_daily_path(today)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(message, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error("ShortMemoryStore.append failed: %s", e)

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
        return self._read_jsonl(self.get_daily_path(date.today()))

    def load_daily(self, d: date) -> list[dict[str, Any]]:
        return self._read_jsonl(self.get_daily_path(d))

    def count_today_lines(self) -> int:
        path = self.get_daily_path(date.today())
        try:
            with open(path, "r", encoding="utf-8") as f:
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
        month_dir = self._base_dir / d.strftime("%Y-%m")
        return month_dir / f"{d.isoformat()}.jsonl"

    def get_month_dir(self, d: date) -> Path:
        return self._base_dir / d.strftime("%Y-%m")

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
        """Return all dates that have .jsonl files, newest first."""
        dates: list[date] = []
        for month_dir in reversed(self.list_month_dirs()):
            for f in reversed(self.list_daily_files(month_dir)):
                try:
                    dates.append(date.fromisoformat(f.stem))
                except ValueError:
                    continue
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
    # Internal
    # ------------------------------------------------------------------

    def _ensure_today_file(self) -> None:
        path = self.get_daily_path(self._today)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.touch()
            logger.debug("Created daily file: %s", path.name)

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
