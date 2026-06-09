"""HTTP/3 → ASGI bridge.

Преобразование событий ``aioquic.h3.events`` в ASGI-scope/receive/send,
понятные FastAPI-приложению. Реализует подмножество ASGI 3.0 HTTP scope
(spec: https://asgi.readthedocs.io/en/latest/specs/www.html).

Минимально поддерживается:
- ``http`` ASGI scope (request/response с body chunks);
- ``http.disconnect`` событие при закрытии QUIC stream.

WebTransport-сессии (extended CONNECT) обрабатываются отдельно в
``webtransport.py`` — здесь только HTTP-семантика.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

from src.backend.core.logging import get_logger

logger = get_logger(__name__)

ASGISend = Callable[[dict[str, Any]], Awaitable[None]]
ASGIReceive = Callable[[], Awaitable[dict[str, Any]]]
ASGIApp = Callable[[dict[str, Any], ASGIReceive, ASGISend], Awaitable[None]]


class HttpStreamHandler:
    """Контекст одного HTTP/3 stream'а (один request/response).

    Поддерживает стриминговый body — ASGI receive/send используют
    ``asyncio.Queue``, что позволяет SSE/chunked-передачу.
    """

    def __init__(
        self,
        *,
        stream_id: int,
        scope: dict[str, Any],
        send_headers: Callable[[int, list[tuple[bytes, bytes]]], None],
        send_data: Callable[[bytes, bool], None],
    ) -> None:
        self.stream_id = stream_id
        self.scope = scope
        self._send_headers = send_headers
        self._send_data = send_data
        self._receive_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._headers_sent = False
        self._closed = False

    async def receive(self) -> dict[str, Any]:
        """ASGI receive() — отдаёт следующий http.request / http.disconnect."""
        return await self._receive_queue.get()

    async def send(self, message: dict[str, Any]) -> None:
        """ASGI send() — обработка http.response.start / http.response.body."""
        match message.get("type"):
            case "http.response.start":
                if self._headers_sent:
                    raise RuntimeError("HTTP/3: повторный response.start запрещён")
                status = int(message["status"])
                headers: list[tuple[bytes, bytes]] = [
                    (b":status", str(status).encode("ascii"))
                ]
                for name, value in message.get("headers", []):
                    headers.append((name.lower(), value))
                self._send_headers(status, headers)
                self._headers_sent = True
            case "http.response.body":
                body = message.get("body", b"")
                more = bool(message.get("more_body", False))
                self._send_data(body, not more)
                if not more:
                    self._closed = True
            case _ as unknown:
                logger.debug("HTTP/3 ASGI: unsupported message type %s", unknown)

    async def push_request(self, body: bytes, more_body: bool) -> None:
        """Положить очередной фрагмент тела запроса в receive-очередь."""
        await self._receive_queue.put(
            {"type": "http.request", "body": body, "more_body": more_body}
        )

    async def push_disconnect(self) -> None:
        """Сообщить ASGI-приложению о закрытии соединения."""
        await self._receive_queue.put({"type": "http.disconnect"})


def build_http_scope(
    *,
    method: str,
    raw_path: bytes,
    headers: list[tuple[bytes, bytes]],
    client: tuple[str, int] | None,
    server: tuple[str, int],
    root_path: str = "",
) -> dict[str, Any]:
    """Собрать ASGI ``http``-scope из QUIC HeadersReceived."""
    parsed = urlsplit(raw_path.decode("ascii", errors="replace"))
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "3",
        "method": method.upper(),
        "scheme": "https",
        "path": parsed.path or "/",
        "raw_path": raw_path,
        "query_string": parsed.query.encode("ascii"),
        "root_path": root_path,
        "headers": [
            (name, value) for name, value in headers if not name.startswith(b":")
        ],
        "client": client,
        "server": server,
        "extensions": {"http.response.push": {}, "http.response.trailers": {}},
    }
