"""Local file-based long-term memory storage with 4 independent files.

Manages user_instructions, user_profile, facts_and_decisions, and
topics_and_interests as separate Markdown files under the Skill's
``long_term/`` directory.

All operations are synchronous local I/O -- no network calls.
"""

from __future__ import annotations

import re
from pathlib import Path

from storage.base import IStorage
from utils.logger import logger

VALID_FILES = frozenset({
    "user_instructions",
    "user_profile",
    "facts_and_decisions",
    "topics_and_interests",
})


class LocalMemoryStore(IStorage):
    """Read / write 4 independent long-term memory Markdown files."""

    def __init__(self, base_dir: str | Path) -> None:
        super().__init__(base_dir)
        self._cache: dict[str, str] = {}
        self._load_all_caches()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_file_path(self, name: str) -> Path:
        self._validate_name(name)
        return self._base_dir / f"{name}.md"

    def read_file(self, name: str) -> str:
        """Return cached content of a named memory file."""
        self._validate_name(name)
        if name in self._cache:
            return self._cache[name]
        text = self.read_text(f"{name}.md")
        self._cache[name] = text
        return text

    def write_file(self, name: str, content: str) -> bool:
        """Overwrite a named memory file (no diff check)."""
        self._validate_name(name)
        try:
            self.write_text(f"{name}.md", content)
            self._cache[name] = content
            return True
        except Exception as e:
            logger.error("Failed to write %s: %s", name, e)
            return False

    def safe_write(self, name: str, new_content: str) -> tuple[bool, str]:
        """Write with diff check to prevent hallucinated data loss.

        Compares structural entry IDs (headings + bold list items) between
        old and new content.  Blocks the write if entries would be lost.

        Returns (success, message).
        """
        old_content = self.read_file(name)
        if not old_content.strip():
            return self.write_file(name, new_content), "written (was empty)"

        old_ids = self._extract_entry_ids(old_content)
        new_ids = self._extract_entry_ids(new_content)
        lost = old_ids - new_ids

        if lost:
            logger.warning(
                "Diff check failed for %s: %d entries would be lost: %s",
                name, len(lost), lost,
            )
            return False, f"blocked: {len(lost)} entries would be lost: {lost}"

        return self.write_file(name, new_content), "ok"

    def append_to_file(self, name: str, content: str) -> bool:
        """Append content to a named memory file."""
        self._validate_name(name)
        try:
            self.append_text(f"{name}.md", content + "\n")
            self._cache[name] = self._cache.get(name, "") + content + "\n"
            return True
        except Exception as e:
            logger.error("Failed to append to %s: %s", name, e)
            return False

    def is_empty(self, name: str) -> bool:
        return not self.read_file(name).strip()

    def reload(self, name: str | None = None) -> None:
        """Force-reload from disk."""
        if name:
            self._validate_name(name)
            self._cache[name] = self.read_text(f"{name}.md")
        else:
            self._load_all_caches()

    def list_nonempty_files(self) -> list[str]:
        """Return names of files that have content."""
        return [n for n in sorted(VALID_FILES) if not self.is_empty(n)]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_all_caches(self) -> None:
        for name in VALID_FILES:
            text = self.read_text(f"{name}.md")
            self._cache[name] = text
            if text.strip():
                logger.info(
                    "Loaded long-term memory: %s (%d chars)", name, len(text),
                )

    @staticmethod
    def _validate_name(name: str) -> None:
        if name not in VALID_FILES:
            raise ValueError(
                f"Invalid memory file: '{name}'. "
                f"Valid: {sorted(VALID_FILES)}"
            )

    @staticmethod
    def _extract_entry_ids(content: str) -> set[str]:
        """Extract structural entry identifiers from Markdown content.

        Recognises:
        - Markdown headings: ## Section Name
        - List items starting with a bold label: - **Label**: ...
        """
        ids: set[str] = set()
        for line in content.splitlines():
            line = line.strip()
            heading = re.match(r"^#{1,3}\s+(.+)$", line)
            if heading:
                ids.add(heading.group(1).strip())
                continue
            bold_item = re.match(r"^-\s+\*\*(.+?)\*\*", line)
            if bold_item:
                ids.add(bold_item.group(1).strip())
        return ids
