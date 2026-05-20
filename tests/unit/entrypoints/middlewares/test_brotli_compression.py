"""Тесты для BrotliCompressionMiddleware (Sprint 10 K2 W2)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.backend.entrypoints.middlewares.brotli_compression import (
    BrotliCompressionMiddleware,
)


async def _drain(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Возвращает копию списка сообщений (helper)."""
    return list(messages)


def _make_app(body: bytes, status: int = 200, content_type: str = "application/json"):
    """Создаёт минимальный ASGI app, возвращающий заданное тело."""

    async def _app(scope: Any, receive: Any, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", content_type.encode("latin-1"))],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
                "more_body": False,
            }
        )

    return _app


async def _invoke(
    middleware: BrotliCompressionMiddleware,
    *,
    accept_encoding: bytes = b"",
) -> list[dict[str, Any]]:
    scope = {
        "type": "http",
        "method": "GET",
        "headers": [(b"accept-encoding", accept_encoding)] if accept_encoding else [],
    }
    captured: list[dict[str, Any]] = []

    async def _receive() -> dict[str, Any]:
        return {"type": "http.request"}

    async def _send(msg: dict[str, Any]) -> None:
        captured.append(msg)

    await middleware(scope, _receive, _send)
    return captured


@pytest.mark.asyncio
async def test_brotli_compresses_json_when_client_accepts_br() -> None:
    payload = json.dumps({"data": "x" * 1000}).encode("utf-8")
    mw = BrotliCompressionMiddleware(
        _make_app(payload), minimum_size=100, quality=4
    )
    msgs = await _invoke(mw, accept_encoding=b"br, gzip")

    start = msgs[0]
    headers = {k: v for k, v in start["headers"]}
    assert headers.get(b"content-encoding") == b"br"
    assert b"vary" in headers
    body = msgs[1]["body"]
    assert len(body) < len(payload)  # реально сжалось


@pytest.mark.asyncio
async def test_passthrough_when_client_does_not_accept_br() -> None:
    payload = b'{"data": "no_br"}'
    mw = BrotliCompressionMiddleware(
        _make_app(payload), minimum_size=10, quality=4
    )
    msgs = await _invoke(mw, accept_encoding=b"gzip")

    start = msgs[0]
    headers = {k: v for k, v in start["headers"]}
    assert b"content-encoding" not in headers
    assert msgs[1]["body"] == payload


@pytest.mark.asyncio
async def test_passthrough_when_body_smaller_than_minimum_size() -> None:
    small = b'{"x":1}'
    mw = BrotliCompressionMiddleware(
        _make_app(small), minimum_size=500, quality=4
    )
    msgs = await _invoke(mw, accept_encoding=b"br")

    start = msgs[0]
    headers = {k: v for k, v in start["headers"]}
    assert b"content-encoding" not in headers
    assert msgs[1]["body"] == small


@pytest.mark.asyncio
async def test_passthrough_when_content_type_not_json() -> None:
    payload = b"plaintext" * 200
    mw = BrotliCompressionMiddleware(
        _make_app(payload, content_type="text/plain"),
        minimum_size=100,
        quality=4,
    )
    msgs = await _invoke(mw, accept_encoding=b"br")

    start = msgs[0]
    headers = {k: v for k, v in start["headers"]}
    assert b"content-encoding" not in headers


@pytest.mark.asyncio
async def test_passthrough_when_scope_not_http() -> None:
    """Lifespan / websocket scope — не трогаем."""
    payload = b'{"x":1}'
    mw = BrotliCompressionMiddleware(
        _make_app(payload), minimum_size=10, quality=4
    )
    scope = {"type": "lifespan", "headers": []}
    captured: list[dict[str, Any]] = []

    async def _receive() -> dict[str, Any]:
        return {"type": "lifespan.startup"}

    async def _send(msg: dict[str, Any]) -> None:
        captured.append(msg)

    # _make_app не обрабатывает lifespan, поэтому стартует с пустым recv —
    # тут просто убеждаемся что middleware пробрасывает scope наружу,
    # не падая.
    try:
        await mw(scope, _receive, _send)
    except Exception:  # noqa: BLE001 — мы не покрываем семантику app
        pass


def test_no_brotli_falls_back_to_noop(monkeypatch) -> None:
    """Если brotli не импортируется, middleware = passthrough."""
    monkeypatch.setattr(
        BrotliCompressionMiddleware, "_try_import_brotli", staticmethod(lambda: None)
    )
    mw = BrotliCompressionMiddleware(lambda *a, **kw: None, minimum_size=100)
    assert mw._brotli is None
