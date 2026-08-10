"""Unit tests for ResponseCacheMiddleware (cycle 55 pure ASGI)."""


from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.entrypoints.middlewares.response_cache import (
    _USE_XXHASH,
    ResponseCacheMiddleware,
)


def _start_message(send: AsyncMock):
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return msg
    return None


def _body_message(send: AsyncMock):
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.body":
            return msg
    return None


def _downstream_json(body: bytes, status_code: int = 200):
    """Downstream возвращающий JSON response."""
    async def downstream(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return downstream


def _downstream_plain(body: bytes, status_code: int = 200):
    async def downstream(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return downstream


def _make_scope(
    method: str = "GET",
    path: str = "/api",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> dict:
    return {
        "type": "http",
        "method": method,
        "url": f"http://test{path}",
        "path": path,
        "headers": headers or [],
        "query_string": b"",
    }


def _make_receive():
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    return receive


class TestResponseCacheMiddleware:
    """Tests for :class:`ResponseCacheMiddleware` (cycle 55 pure ASGI)."""

    @pytest.fixture
    def middleware(self) -> ResponseCacheMiddleware:
        return ResponseCacheMiddleware(AsyncMock(), max_age=120)

    @pytest.mark.asyncio
    async def test_non_get_passes_through(
        self, middleware: ResponseCacheMiddleware
    ) -> None:
        """Non-GET requests skip caching."""
        app = AsyncMock()
        app.side_effect = _downstream_json(b'{"ok":1}')
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope("POST", "/api"),
            _make_receive(),
            send,
        )

        # Status 200 от downstream (без ETag / Cache-Control).
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200
        # Headers НЕ содержат ETag (cycle 55 invariant).
        headers = dict(start["headers"])
        assert b"etag" not in headers
        assert b"cache-control" not in headers

    @pytest.mark.asyncio
    async def test_non_200_passes_through(
        self, middleware: ResponseCacheMiddleware
    ) -> None:
        """Non-200 GET responses skip caching."""
        app = AsyncMock()
        app.side_effect = _downstream_json(b'{"err":1}', status_code=500)
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope("GET", "/api"),
            _make_receive(),
            send,
        )

        # Status 500 (без ETag / Cache-Control).
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 500

    @pytest.mark.asyncio
    async def test_non_json_passes_through(
        self, middleware: ResponseCacheMiddleware
    ) -> None:
        """Non-JSON GET 200 responses skip caching."""
        app = AsyncMock()
        app.side_effect = _downstream_plain(b"plain text")
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope("GET", "/api"),
            _make_receive(),
            send,
        )

        # Status 200 (text/plain не маскируется).
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200
        headers = dict(start["headers"])
        assert b"content-type" in headers
        assert b"application/json" not in headers.get(b"content-type", b"")

    @pytest.mark.asyncio
    async def test_adds_etag_and_cache_control(
        self, middleware: ResponseCacheMiddleware
    ) -> None:
        """JSON 200 GET adds ETag and Cache-Control headers."""
        app = AsyncMock()
        app.side_effect = _downstream_json(b'{"data":1}')
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope("GET", "/api"),
            _make_receive(),
            send,
        )

        # ETag + Cache-Control добавлены.
        start = _start_message(send)
        headers = dict(start["headers"])
        assert b"etag" in headers
        assert headers[b"cache-control"] == b"public, max-age=120"

        # Body сохранён.
        body = _body_message(send)
        assert body["body"] == b'{"data":1}'

    @pytest.mark.asyncio
    async def test_if_none_match_returns_304(
        self, middleware: ResponseCacheMiddleware
    ) -> None:
        """Matching If-None-Match returns 304."""
        body = b'{"data":1}'

        # Compute expected ETag (same logic as middleware).
        if _USE_XXHASH:
            import xxhash

            expected_etag = f'"{xxhash.xxh64(body).hexdigest()}"'
        else:
            from src.backend.entrypoints.middlewares._body_hash import etag_hash

            expected_etag = etag_hash(body)

        app = AsyncMock()
        app.side_effect = _downstream_json(body)
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope(
                "GET",
                "/api",
                headers=[
                    (b"host", b"test"),
                    (b"if-none-match", expected_etag.encode("latin-1")),
                ],
            ),
            _make_receive(),
            send,
        )

        # 304 Not Modified.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 304
        headers = dict(start["headers"])
        assert headers[b"etag"].decode("latin-1") == expected_etag

    @pytest.mark.asyncio
    async def test_if_none_match_mismatch_returns_200(
        self, middleware: ResponseCacheMiddleware
    ) -> None:
        """Mismatched If-None-Match returns 200 with new ETag."""
        app = AsyncMock()
        app.side_effect = _downstream_json(b'{"data":1}')
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope(
                "GET",
                "/api",
                headers=[
                    (b"host", b"test"),
                    (b"if-none-match", b'"old"'),
                ],
            ),
            _make_receive(),
            send,
        )

        # 200 + новый ETag (не 'old').
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200
        headers = dict(start["headers"])
        assert headers[b"etag"] != b'"old"'
        assert headers[b"cache-control"] == b"public, max-age=120"


class TestResponseCacheMiddlewarePureASGI:
    """Cycle 55: pure ASGI regression-тесты для ResponseCacheMiddleware."""

    @pytest.fixture
    def middleware(self) -> ResponseCacheMiddleware:
        return ResponseCacheMiddleware(AsyncMock(), max_age=120)

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(
        self, middleware: ResponseCacheMiddleware
    ) -> None:
        """Non-HTTP scope (websocket) пробрасывается без caching."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            await send({"type": "websocket.accept"})

        app.side_effect = downstream
        middleware.app = app

        send = AsyncMock()
        await middleware(
            {"type": "websocket", "path": "/ws", "headers": []},
            AsyncMock(),
            send,
        )

        msgs = [c.args[0] for c in send.await_args_list]
        assert any(m["type"] == "websocket.accept" for m in msgs)

    @pytest.mark.asyncio
    async def test_etag_deterministic_for_same_body(
        self, middleware: ResponseCacheMiddleware
    ) -> None:
        """Cycle 55 invariant: ETag deterministic для одного body."""
        app = AsyncMock()
        app.side_effect = _downstream_json(b'{"x":1}')
        middleware.app = app

        send1 = AsyncMock()
        await middleware(_make_scope("GET", "/api"), _make_receive(), send1)
        etag1 = _start_message(send1)["headers"]

        send2 = AsyncMock()
        await middleware(_make_scope("GET", "/api"), _make_receive(), send2)
        etag2 = _start_message(send2)["headers"]

        # Один body → один ETag.
        assert etag1 == etag2

    @pytest.mark.asyncio
    async def test_etag_different_for_different_body(
        self, middleware: ResponseCacheMiddleware
    ) -> None:
        """Cycle 55 invariant: different body → different ETag."""
        app1 = AsyncMock()
        app1.side_effect = _downstream_json(b'{"x":1}')
        app2 = AsyncMock()
        app2.side_effect = _downstream_json(b'{"y":2}')

        mw1 = ResponseCacheMiddleware(app=app1, max_age=120)
        mw2 = ResponseCacheMiddleware(app=app2, max_age=120)

        send1 = AsyncMock()
        await mw1(_make_scope("GET", "/api"), _make_receive(), send1)
        etag1 = dict(_start_message(send1)["headers"])[b"etag"]

        send2 = AsyncMock()
        await mw2(_make_scope("GET", "/api"), _make_receive(), send2)
        etag2 = dict(_start_message(send2)["headers"])[b"etag"]

        # Different bodies → different ETags.
        assert etag1 != etag2

    @pytest.mark.asyncio
    async def test_does_not_call_downstream_after_caching(
        self, middleware: ResponseCacheMiddleware
    ) -> None:
        """Cycle 55 invariant: downstream вызван ОДИН раз."""
        call_count = 0

        async def downstream(scope, receive, send):
            nonlocal call_count
            call_count += 1
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": b'{"x":1}'})

        app = AsyncMock()
        app.side_effect = downstream
        middleware.app = app

        send = AsyncMock()
        await middleware(_make_scope("GET", "/api"), _make_receive(), send)

        # Downstream вызван ОДИН раз (не дважды).
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_content_length_updated_with_etag(
        self, middleware: ResponseCacheMiddleware
    ) -> None:
        """ETag добавлен + Content-Length preserved."""
        body = b'{"x":1}'
        app = AsyncMock()
        app.side_effect = _downstream_json(body)
        middleware.app = app

        send = AsyncMock()
        await middleware(_make_scope("GET", "/api"), _make_receive(), send)

        start = _start_message(send)
        headers = dict(start["headers"])
        assert b"etag" in headers
        # Content-Length сохранён (cycle 55: только headers добавляются,
        # body не модифицируется).
        assert headers[b"content-length"] == str(len(body)).encode("latin-1")
