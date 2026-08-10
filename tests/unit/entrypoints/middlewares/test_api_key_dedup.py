"""Тесты дедупликации APIKeyMiddleware vs AuthRequiredMiddleware (M-1, cycle 47 pure ASGI).

Цель: убедиться, что когда AuthRequiredMiddleware уже установил
``request.state.auth``, APIKeyMiddleware пропускает повторную
валидацию без обращения к ``settings.secure.api_key``.

Cycle 47: pure ASGI rewrite — middleware использует scope['state']
вместо request.state для pure ASGI compatibility.
"""


from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


def _start_message(send: AsyncMock):
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return msg
    return None


def _downstream_ok():
    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})
    return downstream


def _make_scope(
    path: str = "/api/v1/protected",
    state: dict | None = None,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> dict:
    return {
        "type": "http",
        "method": "GET",
        "url": f"http://test{path}",
        "path": path,
        "headers": headers or [],
        **({"state": state} if state is not None else {}),
    }


def _make_receive():
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    return receive


class TestAPIKeyMiddlewareDedup:
    """Tests for M-1 dedup (cycle 47 pure ASGI)."""

    @pytest.mark.asyncio
    async def test_api_key_middleware_skips_when_auth_already_set(self) -> None:
        """state.auth установлен → APIKeyMiddleware вызывает call_next без проверок."""
        from src.backend.entrypoints.middlewares.api_key import APIKeyMiddleware

        middleware = APIKeyMiddleware(app=AsyncMock())
        middleware.compiled_patterns = []

        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope(state={"auth": object()}),  # any truthy
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200  # downstream отработал

    @pytest.mark.asyncio
    async def test_api_key_middleware_validates_when_no_auth(self) -> None:
        """state.auth не установлен → проверяется X-API-Key как раньше."""

        from src.backend.entrypoints.middlewares.api_key import APIKeyMiddleware

        middleware = APIKeyMiddleware(app=AsyncMock())
        middleware.compiled_patterns = []

        send = AsyncMock()
        # Без X-API-Key header → 401 (no-raise, через send).
        await middleware(
            _make_scope(),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 401


class TestAPIKeyMiddlewarePureASGI:
    """Cycle 47: pure ASGI regression-тесты для APIKeyMiddleware."""

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(self) -> None:
        """Non-HTTP scope (websocket) пробрасывается без API key check."""
        from src.backend.entrypoints.middlewares.api_key import APIKeyMiddleware

        app = AsyncMock()

        async def downstream(scope, receive, send):
            await send({"type": "websocket.accept"})

        app.side_effect = downstream
        middleware = APIKeyMiddleware(app=app)
        middleware.compiled_patterns = []

        send = AsyncMock()
        await middleware(
            {"type": "websocket", "path": "/ws", "headers": []},
            AsyncMock(),
            send,
        )

        msgs = [c.args[0] for c in send.await_args_list]
        assert any(m["type"] == "websocket.accept" for m in msgs)

    @pytest.mark.asyncio
    async def test_excluded_route_passes_without_api_key(self) -> None:
        """Excluded route (e.g. /health) → пробрасывается без API key check."""
        from src.backend.entrypoints.middlewares.api_key import APIKeyMiddleware

        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware = APIKeyMiddleware(app=app)
        # Excluded pattern: /health/*

        from re import compile
        middleware.compiled_patterns = [compile("/health")]

        send = AsyncMock()
        await middleware(
            _make_scope(path="/health/liveness"),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_missing_api_key_returns_401(self) -> None:
        """Без X-API-Key header → 401 через send (no-raise, cycle 39)."""
        from src.backend.entrypoints.middlewares.api_key import APIKeyMiddleware

        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream
        middleware = APIKeyMiddleware(app=app)
        middleware.compiled_patterns = []

        send = AsyncMock()
        await middleware(
            _make_scope(),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 401

    @pytest.mark.asyncio
    async def test_valid_api_key_passes_through(self) -> None:
        """Valid X-API-Key → пробрасывает downstream."""
        from src.backend.entrypoints.middlewares.api_key import APIKeyMiddleware

        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware = APIKeyMiddleware(app=app)
        middleware.compiled_patterns = []

        # Mock settings.secure.api_key to known value.
        with patch(
            "src.backend.entrypoints.middlewares.api_key.settings",
        ) as mock_settings:
            mock_settings.secure.api_key = "secret-key-123"
            mock_settings.secure.routes_without_api_key = []

            send = AsyncMock()
            await middleware(
                _make_scope(
                    headers=[(b"x-api-key", b"secret-key-123")],
                ),
                _make_receive(),
                send,
            )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_invalid_api_key_returns_401(self) -> None:
        """Invalid X-API-Key → 401 через send (no-raise)."""
        from src.backend.entrypoints.middlewares.api_key import APIKeyMiddleware

        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream
        middleware = APIKeyMiddleware(app=app)
        middleware.compiled_patterns = []

        with patch(
            "src.backend.entrypoints.middlewares.api_key.settings",
        ) as mock_settings:
            mock_settings.secure.api_key = "correct-key"
            mock_settings.secure.routes_without_api_key = []

            send = AsyncMock()
            await middleware(
                _make_scope(
                    headers=[(b"x-api-key", b"wrong-key")],
                ),
                _make_receive(),
                send,
            )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 401

    @pytest.mark.asyncio
    async def test_does_not_call_downstream_when_unauthenticated(self) -> None:
        """Cycle 47 invariant: при 401 downstream НЕ вызывается."""
        from src.backend.entrypoints.middlewares.api_key import APIKeyMiddleware

        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream
        middleware = APIKeyMiddleware(app=app)
        middleware.compiled_patterns = []

        send = AsyncMock()
        await middleware(
            _make_scope(),
            _make_receive(),
            send,
        )

        # 401 отправлен.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 401

    @pytest.mark.asyncio
    async def test_auth_from_state_auth_dedup(self) -> None:
        """M-1 dedup: state.auth установлен → API key check skipped."""
        from src.backend.entrypoints.middlewares.api_key import APIKeyMiddleware

        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware = APIKeyMiddleware(app=app)
        middleware.compiled_patterns = []

        send = AsyncMock()
        # state.auth установлен (как после AuthRequiredMiddleware).
        # Без X-API-Key header — должно пройти.
        await middleware(
            _make_scope(state={"auth": {"method": "JWT", "principal": "alice"}}),
            _make_receive(),
            send,
        )

        # 200 от downstream (без API key check).
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200
