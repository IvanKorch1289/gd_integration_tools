"""Unit tests for LoginStepUpMiddleware (B-04 fix, cycle 33 pure ASGI).

B-04 fix (cycle 33): step-up auth для ``POST /api/v1/auth/login``:
1. ``X-Step-Up-Token`` header обязателен.
2. Rate-limit 10 attempts / 5 min per IP.
3. CSRF cookie default: ``httponly=True``, ``samesite=strict``.
"""


from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.backend.entrypoints.middlewares.csrf import CSRFMiddleware
from src.backend.entrypoints.middlewares.global_ratelimit import FakeRateLimitChecker
from src.backend.entrypoints.middlewares.login_step_up import (
    LOGIN_PATH,
    LoginStepUpMiddleware,
)


def _start_message(send: AsyncMock) -> dict | None:
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return msg
    return None


def _body_message(send: AsyncMock) -> dict | None:
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.body":
            return msg
    return None


def _downstream_ok(status_code: int = 200, body: bytes = b"ok"):
    """Downstream возвращающий 200 OK."""

    async def downstream(scope, receive, send):
        await send(
            {"type": "http.response.start", "status": status_code, "headers": []},
        )
        await send({"type": "http.response.body", "body": body})

    return downstream


def _make_scope(
    method: str = "POST",
    path: str = LOGIN_PATH,
    headers: list[tuple[bytes, bytes]] | None = None,
    client: tuple[str, int] = ("127.0.0.1", 12345),
) -> dict:
    return {
        "type": "http",
        "method": method,
        "url": f"http://test{path}",
        "path": path,
        "scheme": "http",
        "server": ("test", 80),
        "query_string": b"",
        "headers": headers or [],
        "client": client,
    }


def _make_receive() -> AsyncMock:
    receive = AsyncMock()

    async def impl():
        return {"type": "http.request", "body": b"", "more_body": False}

    receive.side_effect = impl
    return receive


def _make_fake_checker() -> FakeRateLimitChecker:
    """In-memory checker — покрывает rate-limit сценарии без Redis."""
    return FakeRateLimitChecker(max_per_window=10, window_seconds=300.0)


class TestLoginStepUpMissingToken:
    """Тесты: ``X-Step-Up-Token`` header обязателен."""

    @pytest.mark.asyncio
    async def test_post_login_without_token_returns_401(self) -> None:
        """POST /api/v1/auth/login без ``X-Step-Up-Token`` → 401 JSON."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = LoginStepUpMiddleware(app=app, rate_limit_factory=_make_fake_checker)

        send = AsyncMock()
        await mw(
            _make_scope("POST", LOGIN_PATH, headers=[]),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 401, "missing token MUST return 401"

        body = _body_message(send)
        assert body is not None
        parsed = json.loads(body["body"].decode("utf-8"))
        assert parsed["error"] == "step_up_token_required"

        # Downstream НЕ должен быть вызван (запрос отклонён до auth-handler).
        app.assert_not_called()

    @pytest.mark.asyncio
    async def test_post_login_with_empty_token_returns_401(self) -> None:
        """Пустой ``X-Step-Up-Token`` (whitespace only) → 401."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = LoginStepUpMiddleware(app=app, rate_limit_factory=_make_fake_checker)

        send = AsyncMock()
        await mw(
            _make_scope(
                "POST",
                LOGIN_PATH,
                headers=[(b"x-step-up-token", b"   ")],
            ),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 401
        app.assert_not_called()

    @pytest.mark.asyncio
    async def test_options_login_bypasses_step_up(self) -> None:
        """``OPTIONS /api/v1/auth/login`` (CORS preflight) → bypass step-up."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = LoginStepUpMiddleware(app=app, rate_limit_factory=_make_fake_checker)

        send = AsyncMock()
        await mw(
            _make_scope("OPTIONS", LOGIN_PATH, headers=[]),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200
        app.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_login_bypasses_step_up(self) -> None:
        """``GET /api/v1/auth/login`` (не-POST) → bypass (для 405-handler)."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = LoginStepUpMiddleware(app=app, rate_limit_factory=_make_fake_checker)

        send = AsyncMock()
        await mw(
            _make_scope("GET", LOGIN_PATH, headers=[]),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200
        app.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_login_path_bypasses_step_up(self) -> None:
        """Любой другой path → bypass (LoginStepUp только login)."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = LoginStepUpMiddleware(app=app, rate_limit_factory=_make_fake_checker)

        send = AsyncMock()
        await mw(
            _make_scope("POST", "/api/v1/something-else", headers=[]),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200
        app.assert_awaited_once()


class TestLoginStepUpRateLimit:
    """Тесты: per-IP rate-limit 10 attempts / 5 min."""

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_returns_429(self) -> None:
        """Превышение лимита (10 attempts) → 429 + Retry-After."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        checker = _make_fake_checker()
        mw = LoginStepUpMiddleware(app=app, rate_limit_factory=lambda: checker)

        # 10 успешных attempts → 11-й блокируется.
        for _ in range(10):
            send = AsyncMock()
            await mw(
                _make_scope(
                    "POST",
                    LOGIN_PATH,
                    headers=[(b"x-step-up-token", b"tok")],
                ),
                _make_receive(),
                send,
            )
            start = _start_message(send)
            assert start is not None
            assert start["status"] == 200

        # 11-й запрос → 429.
        send = AsyncMock()
        await mw(
            _make_scope(
                "POST",
                LOGIN_PATH,
                headers=[(b"x-step-up-token", b"tok")],
            ),
            _make_receive(),
            send,
        )
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 429, "11-й attempt MUST return 429"

        headers = dict(start["headers"])
        assert b"retry-after" in headers
        retry_after = int(headers[b"retry-after"].decode("latin-1"))
        assert retry_after > 0
        assert b"x-ratelimit-scope" in headers
        assert headers[b"x-ratelimit-scope"] == b"login_step_up"

        body = _body_message(send)
        assert body is not None
        parsed = json.loads(body["body"].decode("utf-8"))
        assert parsed["error"] == "rate_limit_exceeded"

    @pytest.mark.asyncio
    async def test_rate_limit_per_ip_isolated(self) -> None:
        """Разные IP → независимые счётчики."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        checker = _make_fake_checker()
        mw = LoginStepUpMiddleware(app=app, rate_limit_factory=lambda: checker)

        # 10 attempts с IP 1.0.0.1 → лимит.
        for _ in range(10):
            send = AsyncMock()
            await mw(
                _make_scope(
                    "POST",
                    LOGIN_PATH,
                    headers=[(b"x-step-up-token", b"tok")],
                    client=("1.0.0.1", 1234),
                ),
                _make_receive(),
                send,
            )

        # IP 1.0.0.1 → 429.
        send_blocked = AsyncMock()
        await mw(
            _make_scope(
                "POST",
                LOGIN_PATH,
                headers=[(b"x-step-up-token", b"tok")],
                client=("1.0.0.1", 1234),
            ),
            _make_receive(),
            send_blocked,
        )
        start_blocked = _start_message(send_blocked)
        assert start_blocked is not None
        assert start_blocked["status"] == 429

        # IP 2.0.0.2 → bypass (fresh counter).
        send_other = AsyncMock()
        await mw(
            _make_scope(
                "POST",
                LOGIN_PATH,
                headers=[(b"x-step-up-token", b"tok")],
                client=("2.0.0.2", 1234),
            ),
            _make_receive(),
            send_other,
        )
        start_other = _start_message(send_other)
        assert start_other is not None
        assert start_other["status"] == 200, (
            "different IP MUST have separate rate-limit counter"
        )

    @pytest.mark.asyncio
    async def test_xff_header_used_for_client_ip(self) -> None:
        """``X-Forwarded-For`` первый IP используется для лимита."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        checker = _make_fake_checker()
        mw = LoginStepUpMiddleware(app=app, rate_limit_factory=lambda: checker)

        # 10 attempts через XFF 1.0.0.1 → лимит.
        for _ in range(10):
            send = AsyncMock()
            await mw(
                _make_scope(
                    "POST",
                    LOGIN_PATH,
                    headers=[
                        (b"x-step-up-token", b"tok"),
                        (b"x-forwarded-for", b"1.0.0.1, 10.0.0.1"),
                    ],
                    client=("10.0.0.1", 1234),
                ),
                _make_receive(),
                send,
            )

        # 11-й с тем же XFF → 429.
        send = AsyncMock()
        await mw(
            _make_scope(
                "POST",
                LOGIN_PATH,
                headers=[
                    (b"x-step-up-token", b"tok"),
                    (b"x-forwarded-for", b"1.0.0.1, 10.0.0.1"),
                ],
                client=("10.0.0.1", 1234),
            ),
            _make_receive(),
            send,
        )
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 429


class TestLoginStepUpSuccessPath:
    """Тесты: успешный путь через middleware."""

    @pytest.mark.asyncio
    async def test_post_login_with_token_passes_through(self) -> None:
        """POST login с токеном → пробрасывается downstream."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = LoginStepUpMiddleware(app=app, rate_limit_factory=_make_fake_checker)

        send = AsyncMock()
        await mw(
            _make_scope(
                "POST",
                LOGIN_PATH,
                headers=[(b"x-step-up-token", b"valid-step-up-tok")],
            ),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200, "valid token MUST pass to downstream"
        app.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_http_scope_passthrough(self) -> None:
        """WebSocket scope → пробрасывается без проверок."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            await send({"type": "websocket.accept"})

        app.side_effect = downstream
        mw = LoginStepUpMiddleware(app=app, rate_limit_factory=_make_fake_checker)

        send = AsyncMock()
        await mw(
            {"type": "websocket", "path": "/ws", "headers": []},
            AsyncMock(),
            send,
        )

        msgs = [c.args[0] for c in send.await_args_list]
        assert any(m["type"] == "websocket.accept" for m in msgs)


class TestCSRFCookieDefaults:
    """B-04: CSRF cookie по умолчанию ``httponly=True``, ``samesite=strict``."""

    @pytest.mark.asyncio
    async def test_csrf_cookie_has_httponly_and_samesite_strict(self) -> None:
        """Safe method → auto-issued cookie имеет ``HttpOnly`` + ``SameSite=strict``."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            await send(
                {"type": "http.response.start", "status": 200, "headers": []},
            )
            await send({"type": "http.response.body", "body": b"ok"})

        app.side_effect = downstream
        csrf_mw = CSRFMiddleware(app=app, enabled=True)

        send = AsyncMock()
        await csrf_mw(
            _make_scope("GET", "/api/some-page", headers=[]),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        headers = dict(start["headers"])
        assert b"set-cookie" in headers
        cookie_value = headers[b"set-cookie"].decode("latin-1").lower()

        # B-04 invariants: httponly + samesite=strict.
        assert "httponly" in cookie_value
        assert "samesite=strict" in cookie_value
        # Secure flag зависит от settings.app.environment — здесь dev,
        # поэтому Secure НЕ должно быть.
        assert "secure" not in cookie_value
