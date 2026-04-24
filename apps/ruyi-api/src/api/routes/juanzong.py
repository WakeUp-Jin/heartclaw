"""Juanzong (卷宗) file management API for the web console."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from config.settings import get_heartclaw_home
from utils.logger import get_logger

router = APIRouter(prefix="/api/juanzong", tags=["juanzong"])
logger = get_logger("juanzong_api")

SKIP_DIRS = frozenset({
    "__pycache__",
    ".git",
    "node_modules",
    ".DS_Store",
})

SKIP_EXTENSIONS = frozenset({
    ".pyc",
    ".pyo",
})

SKIP_RELATIVE_PATHS = frozenset({
    "tiangong/codex/tmp",
})

SKIP_RELATIVE_PATH_PREFIXES = tuple(f"{path}/" for path in SKIP_RELATIVE_PATHS)


def _safe_resolve(relative_path: str) -> Path:
    """Resolve a relative path within ~/.heartclaw/ and prevent traversal."""
    home = get_heartclaw_home()
    resolved = (home / relative_path).resolve()
    if not str(resolved).startswith(str(home.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal denied")
    return resolved


def _should_skip(entry: Path, rel_path: str) -> bool:
    """Skip unstable runtime artifacts and nodes that the UI should not traverse."""
    if rel_path in SKIP_RELATIVE_PATHS or rel_path.startswith(SKIP_RELATIVE_PATH_PREFIXES):
        return True
    if entry.name in SKIP_DIRS:
        return True
    if entry.suffix in SKIP_EXTENSIONS:
        return True
    try:
        return entry.is_symlink()
    except OSError:
        return True


def _entry_sort_key(path: Path) -> tuple[int, str]:
    """Sort directories before files; treat unreadable entries as directories."""
    try:
        is_file = path.is_file()
    except OSError:
        is_file = False
    return (is_file, path.name.lower())


def _build_tree(root: Path, prefix: str = "") -> dict | None:
    """Recursively build a file tree dict."""
    name = root.name
    rel_path = f"{prefix}/{name}" if prefix else name
    rel_path = rel_path.lstrip("/")

    if rel_path and _should_skip(root, rel_path):
        return None

    try:
        if root.is_file():
            return {"name": name, "type": "file", "path": rel_path}
    except OSError:
        return None

    children = []
    try:
        entries = sorted(root.iterdir(), key=_entry_sort_key)
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
        entries = []

    for entry in entries:
        child_rel_path = f"{rel_path}/{entry.name}" if rel_path else entry.name
        if _should_skip(entry, child_rel_path):
            continue
        child = _build_tree(entry, rel_path)
        if child is not None:
            children.append(child)

    return {"name": name, "type": "directory", "path": rel_path, "children": children}


@router.get("/tree")
async def get_tree():
    """Return the file tree under ~/.heartclaw/."""
    home = get_heartclaw_home()
    if not home.is_dir():
        return {"name": ".heartclaw", "type": "directory", "path": "", "children": []}
    tree = _build_tree(home)
    return tree


@router.get("/file")
async def read_file(path: str = Query(..., description="Relative path within .heartclaw")):
    """Read file content by relative path."""
    resolved = _safe_resolve(path)
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    try:
        content = resolved.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"path": path, "content": content}


class FileWriteRequest(BaseModel):
    path: str
    content: str


@router.put("/file")
async def write_file(req: FileWriteRequest):
    """Write content to a file by relative path."""
    resolved = _safe_resolve(req.path)
    if not resolved.parent.is_dir():
        raise HTTPException(status_code=404, detail=f"Parent directory not found: {req.path}")
    try:
        resolved.write_text(req.content, encoding="utf-8")
        logger.info("File saved: %s (%d bytes)", req.path, len(req.content))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "ok", "path": req.path}
