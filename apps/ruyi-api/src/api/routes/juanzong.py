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


def _safe_resolve(relative_path: str) -> Path:
    """Resolve a relative path within ~/.heartclaw/ and prevent traversal."""
    home = get_heartclaw_home()
    resolved = (home / relative_path).resolve()
    if not str(resolved).startswith(str(home.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal denied")
    return resolved


def _build_tree(root: Path, prefix: str = "") -> dict:
    """Recursively build a file tree dict."""
    name = root.name
    rel_path = f"{prefix}/{name}" if prefix else name
    rel_path = rel_path.lstrip("/")

    if root.is_file():
        return {"name": name, "type": "file", "path": rel_path}

    children = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except PermissionError:
        entries = []

    for entry in entries:
        if entry.name in SKIP_DIRS:
            continue
        if entry.suffix in SKIP_EXTENSIONS:
            continue
        children.append(_build_tree(entry, rel_path))

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
