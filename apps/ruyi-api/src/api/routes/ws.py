"""WebSocket endpoint + ConnectionManager for real-time frontend communication."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from utils.logger import get_logger

router = APIRouter()
logger = get_logger("ws")

# Log file paths (shared Docker volume /logs)
_LOG_DIR = Path(os.environ.get("HEARTCLAW_LOG_DIR", "/logs"))
LOG_FILES: dict[str, Path] = {
    "tiangong": _LOG_DIR / "tiangong-worker.log",
    "ruyi": _LOG_DIR / "ruyi-api.log",
}

# Tiangong: 2026-04-24 10:54:26,973 [tiangong.main] INFO: Config loaded...
_RE_TIANGONG = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s+\[([^\]]+)\]\s+(\w+):\s*(.+)$"
)
# Ruyi: [2026-04-24 04:24:37] INFO heartclaw - === HeartClaw starting ===
_RE_RUYI = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+(\w+)\s+(\S+)\s+-\s+(.+)$"
)


def parse_log_line(line: str, source: str) -> dict[str, str] | None:
    """Parse a single log line into structured data. Returns None for unparseable lines."""
    regex = _RE_TIANGONG if source == "tiangong" else _RE_RUYI
    m = regex.match(line.strip())
    if not m:
        return None
    if source == "tiangong":
        ts, module, level, message = m.groups()
        ts = ts.replace(",", ".")
        return {
            "timestamp": ts,
            "level": level.upper(),
            "message": f"[{module}] {message}",
        }
    else:
        ts, level, module, message = m.groups()
        return {
            "timestamp": ts,
            "level": level.upper(),
            "message": f"{module} - {message}",
        }


def read_last_n_lines(path: Path, n: int = 200) -> list[str]:
    """Efficiently read the last N lines of a file."""
    if not path.is_file():
        return []
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return []
            block_size = 8192
            blocks: list[bytes] = []
            remaining = size
            while remaining > 0 and len(b"".join(blocks).split(b"\n")) <= n + 1:
                read_size = min(block_size, remaining)
                remaining -= read_size
                f.seek(remaining)
                blocks.insert(0, f.read(read_size))
            text = b"".join(blocks).decode("utf-8", errors="replace")
            lines = text.splitlines()
            return lines[-n:] if len(lines) > n else lines
    except Exception:
        return []


class LogFileTailer:
    """Async tail for log files, broadcasting new lines via WebSocket."""

    def __init__(self, conn_manager: "ConnectionManager", poll_interval: float = 1.0) -> None:
        self._manager = conn_manager
        self._poll_interval = poll_interval
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        for source, path in LOG_FILES.items():
            task = asyncio.create_task(self._tail(source, path))
            self._tasks.append(task)
        logger.info("LogFileTailer started for: %s", list(LOG_FILES.keys()))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tasks.clear()

    async def _tail(self, source: str, path: Path) -> None:
        while not path.is_file():
            await asyncio.sleep(self._poll_interval * 5)

        f = open(path, "r", encoding="utf-8", errors="replace")
        f.seek(0, 2)
        try:
            while True:
                line = f.readline()
                if not line:
                    await asyncio.sleep(self._poll_interval)
                    if not path.is_file():
                        break
                    continue
                parsed = parse_log_line(line, source)
                if not parsed:
                    continue
                if self._manager.client_count == 0:
                    continue
                msg = {
                    "type": "container_log",
                    "data": {"source": source, **parsed},
                }
                await self._manager.broadcast(msg)
        finally:
            f.close()


_log_file_tailer: LogFileTailer | None = None


def get_log_file_tailer() -> LogFileTailer:
    global _log_file_tailer
    if _log_file_tailer is None:
        _log_file_tailer = LogFileTailer(manager)
    return _log_file_tailer


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts messages."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)
        logger.info("WebSocket client connected (total: %d)", len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            if ws in self._connections:
                self._connections.remove(ws)
        logger.info("WebSocket client disconnected (total: %d)", len(self._connections))

    async def broadcast(self, message: dict[str, Any]) -> None:
        data = json.dumps(message, ensure_ascii=False)
        async with self._lock:
            stale: list[WebSocket] = []
            for ws in self._connections:
                try:
                    await ws.send_text(data)
                except Exception:
                    stale.append(ws)
            for ws in stale:
                self._connections.remove(ws)

    @property
    def client_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


class WebSocketLogHandler(logging.Handler):
    """Custom logging handler that forwards log records to WebSocket clients."""

    def __init__(self, conn_manager: ConnectionManager) -> None:
        super().__init__()
        self._manager = conn_manager
        self._loop: asyncio.AbstractEventLoop | None = None

    def emit(self, record: logging.LogRecord) -> None:
        if self._manager.client_count == 0:
            return

        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                return

        msg = {
            "type": "log",
            "data": {
                "timestamp": datetime.fromtimestamp(record.created).strftime(
                    "%Y-%m-%d %H:%M:%S.%f"
                )[:-3],
                "level": record.levelname,
                "source": record.name,
                "message": self.format(record),
            },
        }

        try:
            self._loop.create_task(self._manager.broadcast(msg))
        except RuntimeError:
            pass


def install_ws_log_handler() -> None:
    """Attach the WebSocket log handler to the heartclaw root logger."""
    root = logging.getLogger("heartclaw")
    for h in root.handlers:
        if isinstance(h, WebSocketLogHandler):
            return
    handler = WebSocketLogHandler(manager)
    handler.setFormatter(logging.Formatter("%(name)s - %(message)s"))
    root.addHandler(handler)


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(ws)
