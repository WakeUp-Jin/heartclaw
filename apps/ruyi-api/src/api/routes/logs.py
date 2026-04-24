"""REST API for reading recent log file entries."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from api.routes.ws import LOG_FILES, parse_log_line, read_last_n_lines

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("/recent")
async def get_recent_logs(
    source: Literal["tiangong", "ruyi"] = Query(..., description="Log source"),
    lines: int = Query(200, ge=1, le=1000, description="Number of recent lines"),
) -> list[dict[str, str]]:
    path = LOG_FILES.get(source)
    if path is None or not path.is_file():
        return []

    raw_lines = read_last_n_lines(path, lines)
    result: list[dict[str, str]] = []
    for line in raw_lines:
        parsed = parse_log_line(line, source)
        if parsed:
            result.append(parsed)
    return result
