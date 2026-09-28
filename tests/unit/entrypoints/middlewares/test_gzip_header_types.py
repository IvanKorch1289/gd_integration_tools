"""Регрессия: gzip-ответ должен содержать byte-заголовки.

Найдено на живом сервисе. ``GZipCompressionExcludingMiddleware`` пересобирал
``http.response.start`` через ``MutableHeaders.items()``, который отдаёт пары
``(str, str)``, а ASGI требует ``(bytes, bytes)``. Uvicorn падал с
``TypeError: cannot use a bytes pattern on a string-like object`` и рвал
соединение **без ответа**.

Наблюдаемое поведение: ``GET /openapi.json`` с ``Accept-Encoding: gzip``
(то есть ровно то, что шлёт каждый браузер) возвращал HTTP 000 и 0 байт на
теле в 494 КБ, тогда как без gzip — 200. Затрагивался любой ответ больше
``minimum_size``.
"""

from __future__ import annotations

import gzip
import json
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.backend.entrypoints.middlewares.gzip_compression_excluding import (
    GZipCompressionExcludingMiddleware,
)

GZIP_HEADERS = [(b"accept-encoding", b"gzip, deflate, br")]


async def _app(scope: Scope, receive: Receive, send: Send) -> None:
    """ASGI-app, отдающая JSON заданного размера."""
    size: int = scope.get("app", {}).get("payload_size", 4096)  # type: ignore[union-attr]
    body = json.dumps({"data": "x" * size}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("latin-1")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


async def _receive() -> Message:  # pragma: no cover - тело запроса не читается
    return {"type": "http.request", "body": b"", "more_body": False}


async def _drive(
    headers: list[tuple[bytes, bytes]], *, path: str = "/data", payload_size: int = 4096
) -> list[Message]:
    """Прогоняет scope через middleware и возвращает исходящие сообщения."""
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers,
        "app": {"payload_size": payload_size},
    }
    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    middleware: ASGIApp = GZipCompressionExcludingMiddleware(_app)
    await middleware(scope, _receive, send)
    return sent


def _start_of(messages: list[Message]) -> dict[bytes, bytes]:
    """Извлекает http.response.start как dict из bytes-пар."""
    start = next(m for m in messages if m["type"] == "http.response.start")
    return {k.lower(): v for k, v in start["headers"]}


def _assert_bytes_pairs(messages: list[Message]) -> None:
    """Каждая пара заголовков должна быть (bytes, bytes)."""
    start = next(m for m in messages if m["type"] == "http.response.start")
    for name, value in start["headers"]:
        assert isinstance(name, bytes), f"header name must be bytes, got {type(name)}"
        assert isinstance(value, bytes), (
            f"header value must be bytes, got {type(value)}"
        )


class TestGzipHeadersAreBytes:
    """Заголовки пересобранного ответа обязаны быть bytes."""

    async def test_start_message_headers_are_bytes(self) -> None:
        """Строковые заголовки роняют uvicorn — они недопустимы по ASGI."""
        messages = await _drive(GZIP_HEADERS)
        _assert_bytes_pairs(messages)

    async def test_compressed_body_is_gzip_and_length_matches(self) -> None:
        """Тело сжато, Content-Length соответствует фактическому размеру."""
        messages = await _drive(GZIP_HEADERS)
        headers = _start_of(messages)
        body = b"".join(
            m.get("body", b"") for m in messages if m["type"] == "http.response.body"
        )

        assert headers[b"content-encoding"] == b"gzip"
        assert int(headers[b"content-length"]) == len(body)
        assert json.loads(gzip.decompress(body))["data"].startswith("x")

    async def test_vary_header_added(self) -> None:
        """Accept-Encoding добавляется в Vary — кэш не должен отдавать
        сжатый ответ клиенту без gzip и наоборот."""
        messages = await _drive(GZIP_HEADERS)
        vary = _start_of(messages).get(b"vary", b"").lower()
        assert b"accept-encoding" in vary

    async def test_without_gzip_body_passes_through(self) -> None:
        """Без Accept-Encoding тело не сжимается, заголовки остаются bytes."""
        messages = await _drive([(b"accept-encoding", b"identity")])
        _assert_bytes_pairs(messages)
        assert b"content-encoding" not in _start_of(messages)

    async def test_small_body_below_threshold_is_not_compressed(self) -> None:
        """Тело меньше minimum_size уходит как есть, тоже в bytes."""
        messages = await _drive(GZIP_HEADERS, payload_size=10)
        _assert_bytes_pairs(messages)
        assert b"content-encoding" not in _start_of(messages)

    async def test_excluded_paths_bypass_compression(self) -> None:
        """Исключённые пути не сжимаются даже при Accept-Encoding: gzip."""
        messages = await _drive(GZIP_HEADERS, path="/docs")
        _assert_bytes_pairs(messages)
        assert b"content-encoding" not in _start_of(messages)

    async def test_large_body_500_bytes_is_compressed(self) -> None:
        """Граница: тело ровно над minimum_size сжимается и остаётся bytes."""
        messages = await _drive(GZIP_HEADERS, payload_size=600)
        _assert_bytes_pairs(messages)
        assert _start_of(messages)[b"content-encoding"] == b"gzip"


def test_mutable_headers_items_are_str_not_bytes() -> None:
    """Фиксирует причину: ``MutableHeaders.items()`` отдаёт строки.

    Именно это несоответствие раньше уходило в uvicorn как str-заголовки.
    """
    from starlette.datastructures import MutableHeaders

    headers = MutableHeaders(raw=[(b"content-type", b"application/json")])
    for name, value in headers.items():
        assert isinstance(name, str)
        assert isinstance(value, str)


def test_asgi_header_encoding_helper_roundtrips() -> None:
    """Проверяет приём кодирования, которым пользуется middleware."""
    pairs: list[Any] = [("content-encoding", "gzip"), ("content-length", "42")]
    encoded: list[tuple[bytes, bytes]] = [
        (
            k.encode("latin-1") if isinstance(k, str) else k,
            v.encode("latin-1") if isinstance(v, str) else v,
        )
        for k, v in pairs
    ]
    assert encoded == [(b"content-encoding", b"gzip"), (b"content-length", b"42")]
