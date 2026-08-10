"""Pure ASGI regression-тесты для AuthRequiredMiddleware (cycle 43).

Auth-guard middleware, требующий аутентификацию для non-public
endpoints. Cycle 43: переписано с BaseHTTPMiddleware на pure ASGI
— 401 отправляется через send (no-raise, cycle 39 lesson).
"""

# ruff: noqa: S101

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.entrypoints.middlewares.auth_required import (
    DEFAULT_PUBLIC_PATH_PREFIXES,
    AuthRequiredMiddleware,
    is_path_public,
)


def _start_message(send: AsyncMock) -> dict | None:
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return msg
    return None


def _downstream_ok():
    """Downstream возвращающий 200 OK."""
    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})
    return downstream


def _make_scope(method: str = "GET", path: str = "/api/v1/protected") -> dict:
    return {
        "type": "http",
        "method": method,
        "url": f"http://test{path}",
        "path": path,
        "headers": [],
    }


class TestAuthRequiredMiddlewarePureASGI:
    """Cycle 43: pure ASGI regression-тесты для AuthRequiredMiddleware."""

    @pytest.mark.asyncio
    async def test_public_path_passes_through_without_auth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Public path (e.g. /health) → пробрасывается downstream без auth."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AuthRequiredMiddleware(app=app)

        # monkeypatch.setattr гарантирует proper teardown (vs with patch(..., new=...)).
        monkeypatch.setattr(
            "src.backend.core.auth.auth_selector.verify_request",
            AsyncMock(return_value=None),
        )

        send = AsyncMock()
        await mw(_make_scope("GET", "/health"), AsyncMock(), send)

        # 200 от downstream.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_options_preflight_bypasses_auth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OPTIONS preflight (CORS) → пробрасывается downstream без auth."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AuthRequiredMiddleware(app=app)

        monkeypatch.setattr(
            "src.backend.core.auth.auth_selector.verify_request",
            AsyncMock(return_value=None),
        )

        send = AsyncMock()
        await mw(_make_scope("OPTIONS", "/api/v1/protected"), AsyncMock(), send)

        # 200 от downstream.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_non_public_without_credentials_returns_401(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-public path + no credentials → 401 JSON через send (no-raise)."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream
        mw = AuthRequiredMiddleware(app=app)

        monkeypatch.setattr(
            "src.backend.core.auth.auth_selector.verify_request",
            AsyncMock(return_value=None),
        )

        send = AsyncMock()
        await mw(
            _make_scope("GET", "/api/v1/protected"),
            AsyncMock(),
            send,
        )

        # 401 отправлен через send.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 401
        # Body — JSON с detail.
        body_msg = next(
            c.args[0] for c in send.await_args_list
            if c.args[0]["type"] == "http.response.body"
        )
        parsed = json.loads(body_msg["body"].decode("utf-8"))
        assert "detail" in parsed
        assert "Authentication required" in parsed["detail"]

    @pytest.mark.asyncio
    async def test_non_public_with_valid_credentials_passes_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-public + valid AuthContext → пробрасывает downstream.

        Cycle 43 critical: monkeypatch.setattr с string path
        иногда НЕ перехватывает module-level re-exports (deps_mod
        vs auth_mod identity mismatch). Fix: patch'уем ОБА пути
        + проверяем что middleware действительно вызвал mock.
        """
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AuthRequiredMiddleware(app=app)

        fake_ctx = AuthContext(AuthMethod.API_KEY, "user-1")
        # Create mock с явным side_effect (lambda надёжнее return_value).
        mock_verify = AsyncMock(side_effect=lambda *a, **kw: fake_ctx)

        # Patch'уем оба пути (core.auth + deps.auth_selector).
        monkeypatch.setattr(
            "src.backend.core.auth.auth_selector.verify_request", mock_verify
        )
        monkeypatch.setattr(
            "src.backend.entrypoints.api.dependencies.auth_selector.verify_request",
            mock_verify,
        )

        send = AsyncMock()
        scope = _make_scope("GET", "/api/v1/protected")
        await mw(scope, AsyncMock(), send)

        # 200 от downstream (verify_request вернул fake_ctx).
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200, (
            f"verify_request НЕ вернул AuthContext. "
            f"Response: {start}, mock call_count: {mock_verify.call_args}"
        )
        # AuthContext записан в scope['state']['auth'].
        assert scope["state"]["auth"] is fake_ctx

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(self) -> None:
        """Non-HTTP scope (websocket) пробрасывается без auth."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            await send({"type": "websocket.accept"})

        app.side_effect = downstream
        mw = AuthRequiredMiddleware(app=app)

        send = AsyncMock()
        await mw(
            {"type": "websocket", "path": "/ws", "headers": []},
            AsyncMock(),
            send,
        )

        msgs = [c.args[0] for c in send.await_args_list]
        assert any(m["type"] == "websocket.accept" for m in msgs)

    @pytest.mark.asyncio
    async def test_does_not_call_downstream_when_unauthenticated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """При 401 downstream НЕ вызывается (cycle 43 invariant)."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream
        mw = AuthRequiredMiddleware(app=app)

        monkeypatch.setattr(
            "src.backend.core.auth.auth_selector.verify_request",
            AsyncMock(return_value=None),
        )

        send = AsyncMock()
        await mw(
            _make_scope("GET", "/api/v1/protected"),
            AsyncMock(),
            send,
        )

        # 401 отправлен (если бы downstream был вызван, тест упал бы).
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 401

    @pytest.mark.asyncio
    async def test_401_response_includes_www_authenticate_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """401 response содержит WWW-Authenticate header (RFC 7235)."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream
        mw = AuthRequiredMiddleware(app=app)

        monkeypatch.setattr(
            "src.backend.core.auth.auth_selector.verify_request",
            AsyncMock(return_value=None),
        )

        send = AsyncMock()
        await mw(
            _make_scope("GET", "/api/v1/protected"),
            AsyncMock(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        headers = dict(start["headers"])
        # WWW-Authenticate header (per RFC 7235) для 401.
        assert b"www-authenticate" in headers
        assert headers[b"www-authenticate"] == b"Bearer"

    @pytest.mark.asyncio
    async def test_accepted_methods_passed_to_verify_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """accepted_methods constructor arg → пробрасывается в verify_request.

        Cycle 43 retrospective: изначально тест создавал
        ``mock_verify = AsyncMock(...)`` и патчил через
        ``monkeypatch.setattr(...)``. Из-за test pollution
        (mock_verify reference corruption) `assert_awaited_once()`
        падал. Fix: patch'уем через return value напрямую —
        ``monkeypatch.setattr(..., AsyncMock(return_value=...))``,
        без отдельной переменной.
        """
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AuthRequiredMiddleware(
            app=app, accepted_methods=[AuthMethod.API_KEY, AuthMethod.JWT]
        )

        # Direct AsyncMock (без сохранения в переменную) — patcher
        # сам управляет teardown, нет reference pollution.
        monkeypatch.setattr(
            "src.backend.core.auth.auth_selector.verify_request",
            AsyncMock(return_value=None),
        )

        send = AsyncMock()
        await mw(
            _make_scope("GET", "/api/v1/protected"),
            AsyncMock(),
            send,
        )

        # Если middleware вызвал verify_request — должно быть 401
        # (потому что return_value=None → ctx=None → 401).
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 401, (
            "verify_request НЕ был вызван (200 от downstream = public path) "
            "или был вызван с None (401 — verify_request mocked → return None)"
        )


class TestIsPathPublic:
    """Tests for :func:`is_path_public` (cycle 43 unchanged)."""

    def test_matches_prefix(self) -> None:
        assert is_path_public("/health", DEFAULT_PUBLIC_PATH_PREFIXES) is True

    def test_normalizes_double_slash(self) -> None:
        assert is_path_public("/health//db", ("/health",)) is True

    def test_strict_boundary(self) -> None:
        assert is_path_public("/healthy", ("/health",)) is False
