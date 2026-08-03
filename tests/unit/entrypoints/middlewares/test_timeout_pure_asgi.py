"""Pure ASGI regression-тесты для TimeoutMiddleware (cycle 50)."""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from src.backend.entrypoints.middlewares.timeout import TimeoutMiddleware


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


def _downstream_ok():
    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    return downstream


def _downstream_slow(seconds: float):
    """Downstream который sleep'ит seconds перед response."""
    async def downstream(scope, receive, send):
        await asyncio.sleep(seconds)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    return downstream


def _make_scope(path: str = "/api") -> dict:
    return {
        "type": "http",
        "method": "GET",
        "url": f"http://test{path}",
        "path": path,
        "headers": [],
        "query_string": b"",
    }


def _make_receive():
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    return receive


class TestTimeoutMiddlewarePureASGI:
    """Cycle 50: pure ASGI regression-тесты для TimeoutMiddleware."""

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(self) -> None:
        """Non-HTTP scope (websocket) пробрасывается без timeout check."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            await send({"type": "websocket.accept"})

        app.side_effect = downstream
        mw = TimeoutMiddleware(app=app)

        send = AsyncMock()
        await mw(
            {"type": "websocket", "path": "/ws", "headers": []},
            AsyncMock(),
            send,
        )

        msgs = [c.args[0] for c in send.await_args_list]
        assert any(m["type"] == "websocket.accept" for m in msgs)

    @pytest.mark.asyncio
    async def test_fast_response_passes_through(self) -> None:
        """Fast downstream (no delay) → 200 OK, не timeout."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = TimeoutMiddleware(app=app)

        send = AsyncMock()
        await mw(
            _make_scope("/api"),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_global_timeout_exceeded_returns_408(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Downstream sleep > global timeout → 408 через send (no-raise)."""
        from src.backend.core.config.features import feature_flags
        from src.backend.core.config.settings import settings

        monkeypatch.setattr(feature_flags, "per_route_timeout_enabled", False)
        monkeypatch.setattr(settings.secure, "request_timeout", 0.05)

        app = AsyncMock()
        app.side_effect = _downstream_slow(0.5)
        mw = TimeoutMiddleware(app=app)

        send = AsyncMock()
        await mw(
            _make_scope("/api"),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 408
        body = _body_message(send)
        import json
        parsed = json.loads(body["body"].decode("utf-8"))
        assert "Превышено" in parsed["detail"]

    @pytest.mark.asyncio
    async def test_per_route_timeout_used_when_match(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """per_route_timeout_enabled=True + match → route-specific timeout."""
        from src.backend.core.config.features import feature_flags
        from src.backend.core.config.settings import settings

        monkeypatch.setattr(feature_flags, "per_route_timeout_enabled", True)
        monkeypatch.setattr(settings.secure, "request_timeout", 5.0)

        app = AsyncMock()
        app.side_effect = _downstream_slow(0.5)
        # heavy: 0.05s budget
        mw = TimeoutMiddleware(app=app, route_timeouts={"/heavy": 0.05})

        send = AsyncMock()
        await mw(
            _make_scope("/heavy/process"),
            _make_receive(),
            send,
        )

        # 408 от per-route timeout (0.05s).
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 408

    @pytest.mark.asyncio
    async def test_per_route_no_match_uses_global(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """per_route_enabled=True + no match → global default."""
        from src.backend.core.config.features import feature_flags
        from src.backend.core.config.settings import settings

        monkeypatch.setattr(feature_flags, "per_route_timeout_enabled", True)
        monkeypatch.setattr(settings.secure, "request_timeout", 5.0)

        app = AsyncMock()
        app.side_effect = _downstream_ok()
        # /heavy НЕ match'ит /api
        mw = TimeoutMiddleware(app=app, route_timeouts={"/heavy": 0.05})

        send = AsyncMock()
        await mw(
            _make_scope("/api/users"),
            _make_receive(),
            send,
        )

        # Global (5.0s) → 200 OK.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_longest_prefix_wins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """При overlapping prefixes — longest prefix match."""
        from src.backend.core.config.features import feature_flags
        from src.backend.core.config.settings import settings

        monkeypatch.setattr(feature_flags, "per_route_timeout_enabled", True)
        monkeypatch.setattr(settings.secure, "request_timeout", 5.0)

        app = AsyncMock()
        app.side_effect = _downstream_slow(0.5)
        # /api = 5.0s (global too), /api/v1/heavy = 0.05s
        mw = TimeoutMiddleware(
            app=app,
            route_timeouts={"/api": 5.0, "/api/v1/heavy": 0.05},
        )

        send = AsyncMock()
        await mw(
            _make_scope("/api/v1/heavy/process"),
            _make_receive(),
            send,
        )

        # Longest /api/v1/heavy (0.05s) wins → 408.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 408

    @pytest.mark.asyncio
    async def test_empty_registry_uses_global(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty registry → global default (даже при flag=ON)."""
        from src.backend.core.config.features import feature_flags
        from src.backend.core.config.settings import settings

        monkeypatch.setattr(feature_flags, "per_route_timeout_enabled", True)
        monkeypatch.setattr(settings.secure, "request_timeout", 5.0)

        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = TimeoutMiddleware(app=app, route_timeouts={})

        send = AsyncMock()
        await mw(
            _make_scope("/api"),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_none_registry_uses_global(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """None registry → global default."""
        from src.backend.core.config.features import feature_flags
        from src.backend.core.config.settings import settings

        monkeypatch.setattr(feature_flags, "per_route_timeout_enabled", True)
        monkeypatch.setattr(settings.secure, "request_timeout", 5.0)

        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = TimeoutMiddleware(app=app, route_timeouts=None)

        send = AsyncMock()
        await mw(
            _make_scope("/api"),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_disabled_flag_ignores_registry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """per_route_timeout_enabled=False → registry ignored, global only."""
        from src.backend.core.config.features import feature_flags
        from src.backend.core.config.settings import settings

        monkeypatch.setattr(feature_flags, "per_route_timeout_enabled", False)
        monkeypatch.setattr(settings.secure, "request_timeout", 5.0)

        app = AsyncMock()
        app.side_effect = _downstream_ok()
        # registry present, но flag OFF — должен игнорироваться.
        mw = TimeoutMiddleware(app=app, route_timeouts={"/heavy": 0.05})

        send = AsyncMock()
        await mw(
            _make_scope("/heavy/process"),
            _make_receive(),
            send,
        )

        # Global (5.0s) → 200 (registry не применён).
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_408_does_not_break_downstream(self) -> None:
        """Cycle 50 invariant: при 408 downstream cancellation graceful.

        wait_for cancels downstream coroutine при timeout (это
        ожидаемое поведение asyncio.wait_for). Главный invariant:
        408 response отправлен + НЕ propagation CancelledError.
        """
        from src.backend.core.config.features import feature_flags
        from src.backend.core.config.settings import settings

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(feature_flags, "per_route_timeout_enabled", False)
            mp.setattr(settings.secure, "request_timeout", 0.05)

            app = AsyncMock()
            app.side_effect = _downstream_slow(0.5)  # slow, cancelled by timeout
            mw = TimeoutMiddleware(app=app)

            send = AsyncMock()
            await mw(
                _make_scope("/api"),
                _make_receive(),
                send,
            )

        # 408 — downstream coroutine cancelled, no exception propagated.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 408
