"""WebSocket endpoint + ConnectionManager for real-time frontend communication."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from utils.logger import get_logger

router = APIRouter()
logger = get_logger("ws")


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
