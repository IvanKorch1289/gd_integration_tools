"""Тесты ASGI bridge для HTTP/3.

Покрывают преобразование QUIC HeadersReceived → ASGI scope и обратно
``HttpStreamHandler`` → :status / body. Не требуют ``aioquic``.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.backend.entrypoints.http3.asgi_bridge import (
    HttpStreamHandler,
    build_http_scope,
)


class _Sink:
    """Накопитель отправленных HTTP/3 фреймов."""

    def __init__(self) -> None:
        self.headers: list[list[tuple[bytes, bytes]]] = []
        self.body: list[tuple[bytes, bool]] = []

    def send_headers(self, status: int, headers: list[tuple[bytes, bytes]]) -> None:
        self.headers.append(headers)

    def send_data(self, data: bytes, end: bool) -> None:
        self.body.append((data, end))


def test_build_http_scope_parses_path_and_query() -> None:
    scope = build_http_scope(
        method="GET",
        raw_path=b"/api/v1/items?limit=10&offset=20",
        headers=[(b"accept", b"application/json")],
        client=("198.51.100.1", 5555),
        server=("127.0.0.1", 8443),
    )
    assert scope["type"] == "http"
    assert scope["http_version"] == "3"
    assert scope["scheme"] == "https"
    assert scope["method"] == "GET"
    assert scope["path"] == "/api/v1/items"
    assert scope["query_string"] == b"limit=10&offset=20"
    assert (b"accept", b"application/json") in scope["headers"]


def test_build_http_scope_strips_pseudo_headers() -> None:
    scope = build_http_scope(
        method="POST",
        raw_path=b"/x",
        headers=[(b":authority", b"example.com"), (b"content-type", b"text/plain")],
        client=None,
        server=("127.0.0.1", 8443),
    )
    names = {n for n, _ in scope["headers"]}
    assert b":authority" not in names
    assert b"content-type" in names


@pytest.mark.asyncio
async def test_handler_send_response_pipeline() -> None:
    sink = _Sink()
    scope: dict[str, Any] = {"type": "http"}

    handler = HttpStreamHandler(
        stream_id=4,
        scope=scope,
        send_headers=sink.send_headers,
        send_data=sink.send_data,
    )
    await handler.send(
        {"type": "http.response.start", "status": 201, "headers": [(b"x-app", b"gd")]}
    )
    await handler.send(
        {"type": "http.response.body", "body": b"hello", "more_body": False}
    )

    assert sink.headers == [[(b":status", b"201"), (b"x-app", b"gd")]]
    assert sink.body == [(b"hello", True)]


@pytest.mark.asyncio
async def test_handler_rejects_double_start() -> None:
    sink = _Sink()
    handler = HttpStreamHandler(
        stream_id=0,
        scope={"type": "http"},
        send_headers=sink.send_headers,
        send_data=sink.send_data,
    )
    await handler.send({"type": "http.response.start", "status": 200, "headers": []})
    with pytest.raises(RuntimeError, match="response.start"):
        await handler.send(
            {"type": "http.response.start", "status": 200, "headers": []}
        )


@pytest.mark.asyncio
async def test_handler_receive_request_chunks() -> None:
    sink = _Sink()
    handler = HttpStreamHandler(
        stream_id=8,
        scope={"type": "http"},
        send_headers=sink.send_headers,
        send_data=sink.send_data,
    )
    await handler.push_request(b"abc", more_body=True)
    await handler.push_request(b"def", more_body=False)

    chunk1 = await handler.receive()
    chunk2 = await handler.receive()
    assert chunk1 == {"type": "http.request", "body": b"abc", "more_body": True}
    assert chunk2 == {"type": "http.request", "body": b"def", "more_body": False}
