"""Unit tests for RequestBodyCacheMiddleware (cycle 52 pure ASGI)."""


from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.entrypoints.middlewares.request_body_cache import (
    RequestBodyCacheMiddleware,
    cached_body,
)


def _start_message(send: AsyncMock):
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return msg
    return None


def _downstream_ok():
    async def downstream(scope, receive, send):
        # Consume replay body to verify it's available.
        more_body = True
        while more_body:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                break
            more_body = msg.get("more_body", False)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    return downstream


def _make_scope(
    method: str = "POST",
    path: str = "/path",
    headers: list[tuple[bytes, bytes]] | None = None,
    state: dict | None = None,
) -> dict:
    return {
        "type": "http",
        "method": method,
        "url": f"http://test{path}",
        "path": path,
        "headers": headers or [],
        "query_string": b"",
        **({"state": state} if state is not None else {}),
    }


def _make_receive(body: bytes = b""):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return receive


class TestRequestBodyCacheMiddleware:
    """Tests for :class:`RequestBodyCacheMiddleware` (cycle 52 pure ASGI)."""

    @pytest.fixture
    def middleware(self) -> RequestBodyCacheMiddleware:
        return RequestBodyCacheMiddleware(AsyncMock(), max_body_size=1024)

    @pytest.mark.asyncio
    async def test_bodyless_methods_skip(
        self, middleware: RequestBodyCacheMiddleware,
    ) -> None:
        """GET/HEAD/OPTIONS/DELETE/TRACE skip caching."""
        for method in ("GET", "HEAD", "OPTIONS", "DELETE", "TRACE"):
            app = AsyncMock()
            app.side_effect = _downstream_ok()
            middleware.app = app

            send = AsyncMock()
            await middleware(
                _make_scope(method, "/path"),
                _make_receive(b""),
                send,
            )

            # Нет body в scope state.
            scope = _make_scope(method, "/path")
            assert cached_body(scope) is None

    @pytest.mark.asyncio
    async def test_content_length_too_large(
        self, middleware: RequestBodyCacheMiddleware,
    ) -> None:
        """Large Content-Length skips caching."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope(
                "POST",
                "/path",
                headers=[(b"content-length", b"2048")],
            ),
            _make_receive(b"x" * 2048),
            send,
        )

        # 200 OK от downstream.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200
        # Body НЕ кэширован (content-length > max).
        assert cached_body(_make_scope("POST", "/path")) is None

    @pytest.mark.asyncio
    async def test_normal_body_cached_and_replay_installed(
        self, middleware: RequestBodyCacheMiddleware,
    ) -> None:
        """Normal body cached в state['body'] + replay receive установлен."""
        app = AsyncMock()

        # Используем свой downstream чтобы проверить replay body.
        captured_body = {}

        async def downstream(scope, receive, send):
            more_body = True
            while more_body:
                msg = await receive()
                if msg["type"] == "http.disconnect":
                    break
                captured_body.setdefault("chunks", []).append(msg.get("body", b""))
                more_body = msg.get("more_body", False)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        app.side_effect = downstream
        middleware.app = app

        send = AsyncMock()
        scope = _make_scope("POST", "/path")
        await middleware(
            scope,
            _make_receive(b"hello"),
            send,
        )

        # state['body'] кэширован.
        assert cached_body(scope) == b"hello"
        # 2026-08-14 fix: replay receive переехал из scope["replay_receive"]
        # в scope["receive"] (FastAPI читает scope["receive"], не отдельный
        # replay ключ). original сохраняется в scope["original_receive"].
        assert "original_receive" in scope
        assert scope["receive"] is not scope["original_receive"]
        # Downstream получил body через replay.
        assert b"".join(captured_body["chunks"]) == b"hello"

    @pytest.mark.asyncio
    async def test_body_exceeds_max_after_read(
        self, middleware: RequestBodyCacheMiddleware,
    ) -> None:
        """Body прочитан но > max: replay installed, NOT cached."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        send = AsyncMock()
        scope = _make_scope("POST", "/path")
        await middleware(
            scope,
            _make_receive(b"x" * 2048),
            send,
        )

        # Body > max → НЕ кэширован.
        assert cached_body(scope) is None
        # 2026-08-14 fix: replay receive переехал в scope["receive"].
        # Даже без кэша downstream не должен повиснуть — replay_receive
        # всё равно установлен (для случая когда body > max но уже прочитан).
        assert "original_receive" in scope
        assert scope["receive"] is not scope["original_receive"]

    @pytest.mark.asyncio
    async def test_body_read_failure(
        self, middleware: RequestBodyCacheMiddleware,
    ) -> None:
        """Failure to read body passes through gracefully (cycle 52 invariant)."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            # НЕ consume body — receive() бросает, и мы просто return.
            await send(
                {"type": "http.response.start", "status": 200, "headers": []},
            )
            await send({"type": "http.response.body", "body": b"ok"})

        app.side_effect = downstream
        middleware.app = app

        async def _bad_receive() -> dict[str, Any]:
            raise RuntimeError("recv error")

        send = AsyncMock()
        await middleware(
            _make_scope("POST", "/path"),
            _bad_receive,
            send,
        )

        # 200 от downstream (graceful fallback после receive error).
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    def test_parse_content_length_valid(
        self, middleware: RequestBodyCacheMiddleware,
    ) -> None:
        """_parse_content_length returns int for valid header."""
        scope = _make_scope(
            "POST", "/path", headers=[(b"content-length", b"42")],
        )
        assert middleware._parse_content_length(scope) == 42

    def test_parse_content_length_missing(
        self, middleware: RequestBodyCacheMiddleware,
    ) -> None:
        """_parse_content_length returns None when header absent."""
        scope = _make_scope("POST", "/path", headers=[])
        assert middleware._parse_content_length(scope) is None

    def test_parse_content_length_invalid(
        self, middleware: RequestBodyCacheMiddleware,
    ) -> None:
        """_parse_content_length returns None for invalid value."""
        scope = _make_scope(
            "POST", "/path", headers=[(b"content-length", b"abc")],
        )
        assert middleware._parse_content_length(scope) is None

    @pytest.mark.asyncio
    async def test_install_replay_receive(
        self, middleware: RequestBodyCacheMiddleware,
    ) -> None:
        """_install_replay_receive provides correct ASGI messages в scope."""
        scope = _make_scope("POST", "/path")
        original = _make_receive()
        replay = middleware._install_replay_receive(scope, original, b"payload")

        # 2026-08-14 fix: scope["receive"] теперь replay_receive (раньше original_receive).
        # scope["original_receive"] = original raw channel (new key для downstream).
        assert scope["receive"] is replay
        assert scope["original_receive"] is original

        # replay_receive возвращает http.request с body, потом http.disconnect.
        msg1 = await replay()
        assert msg1 == {"type": "http.request", "body": b"payload", "more_body": False}
        msg2 = await replay()
        assert msg2 == {"type": "http.disconnect"}


class TestCachedBodyHelper:
    """Tests for :func:`cached_body` (cycle 52 helper)."""

    def test_returns_cached_bytes(self) -> None:
        """Returns cached body when present."""
        scope = _make_scope("POST", "/path", state={"body": b"cached"})
        assert cached_body(scope) == b"cached"

    def test_returns_none_when_missing(self) -> None:
        """Returns None when body is not cached."""
        scope = _make_scope("POST", "/path", state={})
        assert cached_body(scope) is None

    def test_returns_none_for_wrong_type(self) -> None:
        """Returns None when body is not bytes-like."""
        scope = _make_scope("POST", "/path", state={"body": "string"})
        assert cached_body(scope) is None

    def test_returns_none_when_state_missing(self) -> None:
        """Returns None when scope не имеет 'state'."""
        scope = _make_scope("POST", "/path")
        # Force no state.
        scope.pop("state", None)
        assert cached_body(scope) is None


class TestRequestBodyCacheMiddlewarePureASGI:
    """Cycle 52: pure ASGI regression-тесты для RequestBodyCacheMiddleware."""

    @pytest.fixture
    def middleware(self) -> RequestBodyCacheMiddleware:
        return RequestBodyCacheMiddleware(AsyncMock(), max_body_size=1024)

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(
        self, middleware: RequestBodyCacheMiddleware,
    ) -> None:
        """Non-HTTP scope (websocket) пробрасывается без body caching."""
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
    async def test_body_cached_in_state_dict(
        self, middleware: RequestBodyCacheMiddleware,
    ) -> None:
        """Cycle 52: cached body в state['body'] (не в request.state)."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        send = AsyncMock()
        scope = _make_scope("POST", "/path")
        await middleware(
            scope,
            _make_receive(b"hello"),
            send,
        )

        # state['body'] кэширован.
        assert cached_body(scope) == b"hello"

    @pytest.mark.asyncio
    async def test_replay_receive_is_scope_receive_for_downstream(
        self, middleware: RequestBodyCacheMiddleware,
    ) -> None:
        """2026-08-14 fix (Task 4 unblock): scope['receive'] = replay_receive.

        Pre-fix: scope['receive'] = original_receive → FastAPI body-parser
        hangs 10 сек на consumed channel → 400 "error parsing the body".
        Post-fix: downstream получает replay через scope['receive'] (не
        через параметр) И через parameter (см. line 149 в middleware).
        """
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        original_receive = _make_receive(b"hello")
        send = AsyncMock()
        scope = _make_scope("POST", "/path")
        await middleware(
            scope,
            original_receive,
            send,
        )

        # 2026-08-14: scope["receive"] теперь replay_receive, не original.
        assert scope["receive"] is not original_receive
        # original сохраняется в scope["original_receive"] (new key).
        assert scope["original_receive"] is original_receive

    @pytest.mark.asyncio
    async def test_downstream_app_receives_replay_receive(
        self, middleware: RequestBodyCacheMiddleware,
    ) -> None:
        """Downstream получает replay_receive как parameter (line 149 fix)."""
        received_receive = []

        async def downstream(scope, receive, send):
            received_receive.append(receive)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware.app = downstream

        send = AsyncMock()
        scope = _make_scope("POST", "/path")
        await middleware(
            scope,
            _make_receive(b"cached"),
            send,
        )

        # Downstream получил replay_receive (тот же, что scope["receive"]).
        assert len(received_receive) == 1
        # Replay receive должен вернуть body при первом вызове.
        msg1 = await received_receive[0]()
        assert msg1["type"] == "http.request"
        assert msg1["body"] == b"cached"
        assert msg1["more_body"] is False

        msg2 = await received_receive[0]()
        assert msg2["type"] == "http.disconnect"
