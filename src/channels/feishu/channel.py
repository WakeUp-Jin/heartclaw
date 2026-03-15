from __future__ import annotations
from concurrent.futures import Future as ConcurrentFuture



import json
import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import Any

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
)

from channels.feishu.event_handler import parse_message_event
from utils import logger


class FeishuChannel:
    name = "feishu"

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        on_message: Callable[[str, str, str], Awaitable[str]] | None = None,
    ):
        self._app_id = app_id
        self._app_secret = app_secret
        self._on_message = on_message
        self._client:Any = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )
        self._ws_client: lark.ws.Client | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._ws_loop: asyncio.AbstractEventLoop | None = None
        self._ws_thread: threading.Thread | None = None
        self._ws_started = threading.Event()
        self._ws_start_error: Exception | None = None
        self._stopping = threading.Event()

    def set_on_message(self, handler: Callable[[str, str, str], Awaitable[str]]) -> None:
        self._on_message = handler

    async def connect(self) -> None:
        if self._ws_thread and self._ws_thread.is_alive():
            logger.info("Feishu WebSocket already running")
            return
        
        # 获取当前正在运行的的时间循环
        self._event_loop = asyncio.get_running_loop()
        self._stopping.clear()
        self._ws_started.clear()
        self._ws_start_error = None

        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._handle_event)
            .build()
        )

        self._ws_client = lark.ws.Client(
            self._app_id,
            self._app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.WARNING,
        )

        def _run_ws_client() -> None:
            try:
                # lark_oapi ws client uses a module-level loop variable; bind it to this thread.
                import lark_oapi.ws.client as ws_client_module

                ws_loop = asyncio.new_event_loop()
                ws_client_module.loop = ws_loop
                asyncio.set_event_loop(ws_loop)
                self._ws_loop = ws_loop
                self._ws_started.set()

                if self._ws_client is None:
                    return
                self._ws_client.start()
            except Exception as exc:
                expected_stop = (
                    self._stopping.is_set()
                    and isinstance(exc, RuntimeError)
                    and "Event loop stopped before Future completed" in str(exc)
                )
                if not expected_stop:
                    self._ws_start_error = exc
                    logger.error("Feishu WebSocket thread exited unexpectedly", exc_info=True)
            finally:
                loop = self._ws_loop
                self._ws_loop = None
                if loop and not loop.is_closed():
                    loop.close()

        self._ws_thread = threading.Thread(
            target=_run_ws_client,
            name="feishu-ws-client",
            daemon=True,
        )
        self._ws_thread.start()
        await asyncio.to_thread(self._ws_started.wait, 2.0)

        if self._ws_start_error is not None:
            raise RuntimeError("Failed to start Feishu WebSocket client") from self._ws_start_error

        logger.info("Feishu WebSocket connected (p2p single-chat mode)")

    def _handle_event(self, data: Any) -> None:
        """Sync callback from lark-oapi, bridge to async."""
        parsed = parse_message_event(data)
        if parsed is None:
            return

        if self._on_message and self._event_loop:
            future = asyncio.run_coroutine_threadsafe(
                self._process_message(parsed), self._event_loop
            )
            future.add_done_callback(self._on_future_done)

    async def _process_message(self, parsed: dict[str, Any]) -> None:
        if not self._on_message:
            return

        text = parsed["text"]
        chat_id = parsed["chat_id"]
        open_id = parsed["open_id"]

        try:
            reply = await self._on_message(text, chat_id, open_id)
            if reply:
                await self.send_message(chat_id, reply)
        except Exception as e:
            logger.error("Error processing message: %s", e, exc_info=True)
            try:
                await self.send_message(chat_id, f"处理消息时出错: {e}")
            except Exception:
                logger.error("Failed to send error reply", exc_info=True)

    @staticmethod
    def _on_future_done(future: ConcurrentFuture[None]) -> None:
        exc = future.exception()
        if exc:
            logger.error("Message processing error: %s", exc, exc_info=True)

    async def send_message(
        self, chat_id: str, content: str, msg_type: str = "text"
    ) -> None:
        if msg_type == "text":
            content_json = json.dumps({"text": content}, ensure_ascii=False)
        else:
            content_json = content

        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type(msg_type)
                .content(content_json)
                .build()
            )
            .build()
        )

        resp = self._client.im.v1.message.create(request)
        if not resp.success():
            logger.error(
                "Failed to send message: code=%s, msg=%s", resp.code, resp.msg
            )

    async def disconnect(self) -> None:
        if not self._ws_client:
            return

        logger.info("Feishu WebSocket disconnecting...")
        self._stopping.set()

        if self._ws_loop and self._ws_loop.is_running():
            self._ws_client._auto_reconnect = False
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._ws_client._disconnect(), self._ws_loop
                )
                await asyncio.wrap_future(future)
            except Exception:
                logger.warning("Failed to disconnect Feishu WebSocket cleanly", exc_info=True)
            finally:
                self._ws_loop.call_soon_threadsafe(self._ws_loop.stop)

        if self._ws_thread and self._ws_thread.is_alive():
            await asyncio.to_thread(self._ws_thread.join, 2.0)

        self._ws_thread = None
        self._ws_client = None
        self._event_loop = None
        self._ws_started.clear()
        self._ws_start_error = None
        self._stopping.clear()

    def is_connected(self) -> bool:
        return self._ws_client is not None
