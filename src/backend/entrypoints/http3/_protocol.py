"""QUIC connection protocol с ASGI bridge.

Обрабатывает события HTTP/3 (``HeadersReceived`` / ``DataReceived`` /
``WebTransportStreamDataReceived``) и преобразует их в ASGI-вызовы.

Класс инстанцируется ``aioquic.asyncio.serve(create_protocol=...)``
для каждого нового QUIC-соединения. Зависимость от ``aioquic``
импортируется при загрузке модуля — он подгружается только из
``serve_http3``-фабрики, поэтому safe для opt-in.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h3.events import (
    DatagramReceived,
    DataReceived,
    H3Event,
    HeadersReceived,
    WebTransportStreamDataReceived,
)
from aioquic.quic.events import ProtocolNegotiated, QuicEvent

from src.backend.entrypoints.http3.asgi_bridge import (
    HttpStreamHandler,
    build_http_scope,
)
from src.backend.entrypoints.http3.config import Http3ServerConfig
from src.backend.infrastructure.logging.factory import get_logger

logger = get_logger(__name__)

ASGIApp = Callable[
    [
        dict[str, Any],
        Callable[[], Awaitable[dict[str, Any]]],
        Callable[[dict[str, Any]], Awaitable[None]],
    ],
    Awaitable[None],
]


class AsgiHttp3Protocol(QuicConnectionProtocol):
    """ASGI bridge для одного QUIC-соединения.

    Создаёт ``HttpStreamHandler`` на каждый stream и запускает ASGI app
    как отдельную asyncio task. Body-фрагменты доставляются через
    ``asyncio.Queue`` — приложение видит обычный ASGI HTTP.
    """

    def __init__(
        self,
        *args: Any,
        asgi_app: ASGIApp,
        server_config: Http3ServerConfig,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._asgi_app = asgi_app
        self._server_config = server_config
        self._http: H3Connection | None = None
        self._handlers: dict[int, HttpStreamHandler] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def quic_event_received(self, event: QuicEvent) -> None:
        if isinstance(event, ProtocolNegotiated) and event.alpn_protocol in H3_ALPN:
            self._http = H3Connection(self._quic, enable_webtransport=True)
        if self._http is not None:
            for h3_event in self._http.handle_event(event):
                self._handle_h3_event(h3_event)

    def _handle_h3_event(self, event: H3Event) -> None:
        match event:
            case HeadersReceived(stream_id=sid, headers=headers, stream_ended=ended):
                self._on_headers(sid, headers, ended)
            case DataReceived(stream_id=sid, data=data, stream_ended=ended):
                self._on_data(sid, data, ended)
            case WebTransportStreamDataReceived() | DatagramReceived():
                # WebTransport: see webtransport.py — заглушка-handler.
                logger.debug("WebTransport event ignored: %s", type(event).__name__)
            case _:
                logger.debug("Unhandled H3 event: %s", type(event).__name__)

    def _on_headers(
        self, stream_id: int, headers: list[tuple[bytes, bytes]], stream_ended: bool
    ) -> None:
        method = b""
        path = b"/"
        normalised: list[tuple[bytes, bytes]] = []
        for name, value in headers:
            if name == b":method":
                method = value
            elif name == b":path":
                path = value
            elif not name.startswith(b":"):
                normalised.append((name, value))

        scope = build_http_scope(
            method=method.decode("ascii", errors="replace"),
            raw_path=path,
            headers=normalised,
            client=None,
            server=(self._server_config.host, self._server_config.port),
        )

        def _send_headers(
            status: int, hdrs: list[tuple[bytes, bytes]], sid: int = stream_id
        ) -> None:
            self._send_headers(sid, hdrs)

        def _send_data(body: bytes, end: bool, sid: int = stream_id) -> None:
            self._send_data(sid, body, end)

        handler = HttpStreamHandler(
            stream_id=stream_id,
            scope=scope,
            send_headers=_send_headers,
            send_data=_send_data,
        )
        self._handlers[stream_id] = handler

        from src.backend.core.utils.task_registry import get_task_registry

        registry = get_task_registry()
        if stream_ended:
            push_task = registry.create_task(
                handler.push_request(b"", more_body=False),
                name=f"http3-push-empty-{stream_id}",
            )
            self._tasks.add(push_task)
            push_task.add_done_callback(self._tasks.discard)

        task = registry.create_task(
            self._asgi_app(scope, handler.receive, handler.send),
            name=f"http3-asgi-stream-{stream_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _on_data(self, stream_id: int, data: bytes, stream_ended: bool) -> None:
        handler = self._handlers.get(stream_id)
        if handler is None:
            return
        from src.backend.core.utils.task_registry import get_task_registry

        registry = get_task_registry()
        push_task = registry.create_task(
            handler.push_request(data, more_body=not stream_ended),
            name=f"http3-push-data-{stream_id}",
        )
        self._tasks.add(push_task)
        push_task.add_done_callback(self._tasks.discard)
        if stream_ended:
            disc_task = registry.create_task(
                handler.push_disconnect(), name=f"http3-push-disconnect-{stream_id}"
            )
            self._tasks.add(disc_task)
            disc_task.add_done_callback(self._tasks.discard)

    def _send_headers(self, stream_id: int, headers: list[tuple[bytes, bytes]]) -> None:
        if self._http is None:
            return
        self._http.send_headers(stream_id=stream_id, headers=headers, end_stream=False)
        self.transmit()

    def _send_data(self, stream_id: int, data: bytes, end_stream: bool) -> None:
        if self._http is None:
            return
        self._http.send_data(stream_id=stream_id, data=data, end_stream=end_stream)
        self.transmit()
