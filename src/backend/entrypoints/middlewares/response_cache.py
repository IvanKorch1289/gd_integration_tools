"""Middleware для HTTP-кэширования GET-ответов (cycle 55 pure ASGI).

Добавляет заголовки ETag и Cache-Control к GET-ответам
с Content-Type: application/json. Поддерживает условные
запросы через If-None-Match.

Cycle 55: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с cycle 33-54 (L1 middlewares).

Cycle 55 design: response headers modification через send-wrapper.
3 headers: ETag, Cache-Control, и conditional If-None-Match → 304.

В BaseHTTPMiddleware версии middleware использовал
``response.body_iterator = async_chunk_iterator([body])`` (магический
Starlette API) для restore body. В pure ASGI нет body_iterator —
только suppression + re-send pattern (аналог cycle 54 PII).

Однако cycle 55 ОТЛИЧАЕТСЯ: response НЕ модифицируется (только
headers добавляются). Можно: добавить headers через send-wrapper
(start message), и downstream-consumers получат body как есть
(т.к. body НЕ модифицируется, можно не suppress + re-send).
"""

from __future__ import annotations

try:
    import xxhash

    _USE_XXHASH = True
except ImportError:

    _USE_XXHASH = False

from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ("ResponseCacheMiddleware",)


class ResponseCacheMiddleware:
    """Pure ASGI middleware: HTTP-кэширование GET-ответов через ETag (cycle 55).

    Args:
        app: ASGI-приложение.
        max_age: TTL в секундах для Cache-Control.
    """

    def __init__(self, app: ASGIApp, max_age: int = 60) -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.
            max_age: TTL в секундах для Cache-Control.
        """
        self.app = app
        self._max_age = max_age

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process HTTP caching for GET responses.

        Args:
            scope: ASGI scope.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")

        # Non-GET requests skip caching.
        if method != "GET":
            await self.app(scope, receive, send)
            return

        # Cycle 55 critical: collect body chunks через send-wrapper
        # для вычисления ETag. Pure ASGI: body приходит через
        # http.response.body messages.
        body_chunks: list[bytes] = []
        response_status: dict[str, int] = {"status": 0}
        response_headers: list[tuple[bytes, bytes]] = []
        content_type: dict[str, str] = {"value": ""}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_status["status"] = message.get("status", 200)
                for k, v in message.get("headers", []):
                    response_headers.append((k, v))
                    if k.lower() == b"content-type":
                        content_type["value"] = v.decode("latin-1", errors="replace")
                # Suppress original start — мы отправим свой с ETag + Cache-Control.
            elif message["type"] == "http.response.body":
                if content_type["value"] and "application/json" in content_type["value"]:
                    body_chunks.append(message.get("body", b""))
                # Cycle 55: пропускаем body downstream (он не модифицирован).
                # Соберём в конце и отправим с обновлённым ETag + Cache-Control headers.
            # НО для простоты в cycle 55 — используем suppress pattern:
                # пропускаем (мы отправим сами в конце).
            else:
                pass  # ignore other message types

        # Пробрасываем downstream (collect headers + body через send_wrapper).
        await self.app(scope, receive, send_wrapper)

        # Cycle 55 logic: пропустить non-200 или non-JSON → отправляем original.
        if response_status["status"] != 200:
            # Skip caching — re-send original response.
            await self._send_original(
                send, response_status["status"], response_headers, body_chunks
            )
            return

        if "application/json" not in content_type["value"]:
            # Non-JSON — skip caching.
            await self._send_original(
                send, response_status["status"], response_headers, body_chunks
            )
            return

        # Compute ETag.
        body = b"".join(body_chunks)
        if not body:
            return

        if _USE_XXHASH:
            etag = f'"{xxhash.xxh64(body).hexdigest()}"'
        else:
            from src.backend.entrypoints.middlewares._body_hash import etag_hash

            etag = etag_hash(body)

        # Cycle 55: If-None-Match check.
        if_none_match = _get_header_value(scope, b"if-none-match")
        if if_none_match and if_none_match == etag:
            # 304 Not Modified.
            await send(
                {
                    "type": "http.response.start",
                    "status": 304,
                    "headers": [(b"etag", etag.encode("latin-1"))],
                }
            )
            return

        # Cycle 55: new response с ETag + Cache-Control.
        new_headers: list[tuple[bytes, bytes]] = []
        for k, v in response_headers:
            if k.lower() in (b"etag", b"cache-control"):
                continue
            new_headers.append((k, v))
        new_headers.append((b"etag", etag.encode("latin-1")))
        new_headers.append(
            (b"cache-control", f"public, max-age={self._max_age}".encode("latin-1"))
        )

        await send(
            {
                "type": "http.response.start",
                "status": response_status["status"],
                "headers": new_headers,
            }
        )
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    async def _send_original(
        send: Send,
        status: int,
        original_headers: list[tuple[bytes, bytes]],
        body_chunks: list[bytes],
    ) -> None:
        """Re-send original response (cycle 55 helper для non-cached paths)."""
        await send(
            {"type": "http.response.start", "status": status, "headers": original_headers}
        )
        if body_chunks:
            await send(
                {
                    "type": "http.response.body",
                    "body": b"".join(body_chunks),
                }
            )


def _get_header_value(scope: Scope, name: bytes) -> str:
    """Извлекает header из ASGI scope (cycle 43 helper)."""
    for header_name, header_value in scope.get("headers", []):
        if header_name == name:
            try:
                return header_value.decode("latin-1")
            except UnicodeDecodeError:
                return ""
    return ""
