"""Unit tests for CSRFMiddleware (cycle 57 pure ASGI)."""


from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.entrypoints.middlewares.csrf import CSRFMiddleware


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


def _downstream_ok(status_code: int = 200, body: bytes = b"ok"):
    async def downstream(scope, receive, send):
        await send(
            {"type": "http.response.start", "status": status_code, "headers": []},
        )
        await send({"type": "http.response.body", "body": body})

    return downstream


def _make_scope(
    method: str = "GET",
    path: str = "/path",
    headers: list[tuple[bytes, bytes]] | None = None,
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
    }


def _make_receive():
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    return receive


class TestCSRFMiddleware:
    """Tests for :class:`CSRFMiddleware` (cycle 57 pure ASGI)."""

    @pytest.fixture
    def middleware(self) -> CSRFMiddleware:
        return CSRFMiddleware(AsyncMock(), enabled=True)

    @pytest.mark.asyncio
    async def test_safe_method_get_bypasses_csrf(
        self, middleware: CSRFMiddleware,
    ) -> None:
        """GET bypasses CSRF check + auto-issues cookie."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        send = AsyncMock()
        with patch("secrets.token_urlsafe", return_value="csrf-tok-123"):
            await middleware(
                _make_scope("GET", "/api"),
                _make_receive(),
                send,
            )

        # 200 от downstream.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200
        # CSRF cookie auto-issued.
        headers = dict(start["headers"])
        assert b"set-cookie" in headers
        assert b"csrf-tok-123" in headers[b"set-cookie"]

    @pytest.mark.asyncio
    async def test_safe_method_head_bypasses_csrf(
        self, middleware: CSRFMiddleware,
    ) -> None:
        """HEAD bypasses CSRF check."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope("HEAD", "/api"),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_safe_method_options_bypasses_csrf(
        self, middleware: CSRFMiddleware,
    ) -> None:
        """OPTIONS bypasses CSRF check (CORS preflight)."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope("OPTIONS", "/api"),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_post_without_csrf_returns_403(
        self, middleware: CSRFMiddleware,
    ) -> None:
        """POST без CSRF token → 403 (no-raise, cycle 39 pattern)."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope("POST", "/api"),
            _make_receive(),
            send,
        )

        # 403 через send.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 403
        body = _body_message(send)
        parsed = json.loads(body["body"].decode("utf-8"))
        assert parsed["error"] == "csrf_token_missing"

    @pytest.mark.asyncio
    async def test_post_with_matching_csrf_passes(
        self, middleware: CSRFMiddleware,
    ) -> None:
        """POST с matching cookie+header → 200 (cycle 57 invariant)."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope(
                "POST",
                "/api",
                headers=[
                    (b"cookie", b"csrf_token=mytoken"),
                    (b"x-csrf-token", b"mytoken"),
                ],
            ),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_post_with_mismatched_csrf_returns_403(
        self, middleware: CSRFMiddleware,
    ) -> None:
        """POST с mismatched tokens → 403."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope(
                "POST",
                "/api",
                headers=[
                    (b"cookie", b"csrf_token=mytoken"),
                    (b"x-csrf-token", b"wrongtoken"),
                ],
            ),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 403
        body = _body_message(send)
        parsed = json.loads(body["body"].decode("utf-8"))
        assert parsed["error"] == "csrf_token_mismatch"

    @pytest.mark.asyncio
    async def test_post_with_jwt_auth_exempt(
        self, middleware: CSRFMiddleware,
    ) -> None:
        """POST с JWT bearer auth → exempt (не требует CSRF)."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope(
                "POST",
                "/api",
                headers=[(b"authorization", b"Bearer jwt-token")],
            ),
            _make_receive(),
            send,
        )

        # 200 (JWT exempt).
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_post_with_api_key_exempt(
        self, middleware: CSRFMiddleware,
    ) -> None:
        """POST с API key auth → exempt."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope(
                "POST",
                "/api",
                headers=[(b"x-api-key", b"my-api-key")],
            ),
            _make_receive(),
            send,
        )

        # 200 (API key exempt).
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_webhook_safe_path_bypass(
        self, middleware: CSRFMiddleware,
    ) -> None:
        """Path в safe_paths → bypass CSRF."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app
        # Пересоздаём с safe_paths.
        middleware = CSRFMiddleware(
            app=app, enabled=True, safe_paths=["/webhooks/"],
        )

        send = AsyncMock()
        await middleware(
            _make_scope("POST", "/webhooks/stripe"),
            _make_receive(),
            send,
        )

        # 200 (webhook bypass).
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_disabled_middleware_bypasses_all(
        self, middleware: CSRFMiddleware,
    ) -> None:
        """enabled=False → всё пробрасывается без CSRF check."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        disabled_mw = CSRFMiddleware(app=app, enabled=False)

        send = AsyncMock()
        await disabled_mw(
            _make_scope("POST", "/api"),
            _make_receive(),
            send,
        )

        # 200 (CSRF disabled).
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_put_with_csrf_passes(
        self, middleware: CSRFMiddleware,
    ) -> None:
        """PUT с matching CSRF → 200."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope(
                "PUT",
                "/api",
                headers=[
                    (b"cookie", b"csrf_token=tok"),
                    (b"x-csrf-token", b"tok"),
                ],
            ),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_delete_with_csrf_passes(
        self, middleware: CSRFMiddleware,
    ) -> None:
        """DELETE с matching CSRF → 200."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope(
                "DELETE",
                "/api",
                headers=[
                    (b"cookie", b"csrf_token=tok"),
                    (b"x-csrf-token", b"tok"),
                ],
            ),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_patch_with_csrf_passes(
        self, middleware: CSRFMiddleware,
    ) -> None:
        """PATCH с matching CSRF → 200."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope(
                "PATCH",
                "/api",
                headers=[
                    (b"cookie", b"csrf_token=tok"),
                    (b"x-csrf-token", b"tok"),
                ],
            ),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200


class TestCSRFMiddlewarePureASGI:
    """Cycle 57: pure ASGI regression-тесты для CSRFMiddleware."""

    @pytest.fixture
    def middleware(self) -> CSRFMiddleware:
        return CSRFMiddleware(AsyncMock(), enabled=True)

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(
        self, middleware: CSRFMiddleware,
    ) -> None:
        """Non-HTTP scope (websocket) пробрасывается без CSRF check."""
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
    async def test_does_not_call_downstream_when_csrf_invalid(
        self, middleware: CSRFMiddleware,
    ) -> None:
        """Cycle 57 invariant: при CSRF invalid downstream НЕ вызывается."""
        call_count = 0

        async def downstream(scope, receive, send):
            nonlocal call_count
            call_count += 1
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [],
                },
            )
            await send({"type": "http.response.body", "body": b"ok"})

        app = AsyncMock()
        app.side_effect = downstream
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope("POST", "/api"),
            _make_receive(),
            send,
        )

        # CSRF invalid → 403, downstream НЕ вызван.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 403
        assert call_count == 0

    @pytest.mark.asyncio
    async def test_cookie_already_present_no_new_cookie(
        self, middleware: CSRFMiddleware,
    ) -> None:
        """Cookie уже есть → new CSRF cookie НЕ auto-issues."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope(
                "GET",
                "/api",
                headers=[(b"cookie", b"csrf_token=existing")],
            ),
            _make_receive(),
            send,
        )

        # Existing cookie → НЕ auto-issue new.
        start = _start_message(send)
        headers = dict(start["headers"])
        # Нет set-cookie (existing cookie).
        assert b"set-cookie" not in headers

    @pytest.mark.asyncio
    async def test_body_unchanged_in_safe_method(
        self, middleware: CSRFMiddleware,
    ) -> None:
        """Cycle 57 invariant: body не модифицируется в safe method pass-through."""
        app = AsyncMock()
        app.side_effect = _downstream_ok(body=b"original")
        middleware.app = app

        send = AsyncMock()
        with patch("secrets.token_urlsafe", return_value="csrf-tok"):
            await middleware(
                _make_scope("GET", "/api"),
                _make_receive(),
                send,
            )

        # Body unchanged.
        body = _body_message(send)
        assert body["body"] == b"original"
