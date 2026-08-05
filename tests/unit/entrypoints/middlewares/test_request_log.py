"""Unit tests for InnerRequestLoggingMiddleware (cycle 53 pure ASGI)."""

# ruff: noqa: S101

from __future__ import annotations


from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.entrypoints.middlewares.request_log import (
    InnerRequestLoggingMiddleware,
)


def _start_message(send: AsyncMock):
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return msg
    return None


def _downstream_ok(status_code: int = 200, body: bytes = b"ok"):
    async def downstream(scope, receive, send):
        await send(
            {"type": "http.response.start", "status": status_code, "headers": []}
        )
        await send({"type": "http.response.body", "body": body})

    return downstream


def _make_scope(
    method: str = "GET",
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


class TestInnerRequestLoggingMiddleware:
    """Tests for :class:`InnerRequestLoggingMiddleware` (cycle 53 pure ASGI)."""

    @pytest.fixture
    def middleware(self) -> InnerRequestLoggingMiddleware:
        app = AsyncMock()
        mw = InnerRequestLoggingMiddleware(app)
        mw.logger = MagicMock()
        mw.log_body = False
        mw.max_body_size = 1000
        return mw

    @pytest.mark.asyncio
    async def test_logs_request_and_response(
        self, middleware: InnerRequestLoggingMiddleware
    ) -> None:
        """Логирует method/path и response status."""
        app = AsyncMock()
        app.side_effect = _downstream_ok(status_code=200)
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope("GET", "/path"),
            _make_receive(),
            send,
        )

        # Logged: request line.
        assert any(
            "Запрос: GET /path" in str(call)
            for call in middleware.logger.info.call_args_list
        )
        # Logged: response line.
        assert any(
            "Ответ: 200" in str(call)
            for call in middleware.logger.info.call_args_list
        )

    @pytest.mark.asyncio
    async def test_logs_post_body_when_enabled(
        self, middleware: InnerRequestLoggingMiddleware
    ) -> None:
        """log_body=True + POST → логирует body."""
        middleware.log_body = True
        app = AsyncMock()
        app.side_effect = _downstream_ok(status_code=201)
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope(
                "POST",
                "/path",
                headers=[(b"content-type", b"application/json")],
            ),
            _make_receive(b'{"data": 1}'),
            send,
        )

        # log_body=True → _get_request_body вызван.
        assert any(
            "Тело запроса" in str(call)
            for call in middleware.logger.debug.call_args_list
        )

    @pytest.mark.asyncio
    async def test_logs_error_on_exception(
        self, middleware: InnerRequestLoggingMiddleware
    ) -> None:
        """Exception → logger.error + re-raise (cycle 51 invariant)."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise RuntimeError("boom")

        app.side_effect = downstream
        middleware.app = app

        send = AsyncMock()
        with pytest.raises(RuntimeError, match="boom"):
            await middleware(
                _make_scope("GET", "/path"),
                _make_receive(),
                send,
            )

        middleware.logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_request_body_from_cache(
        self, middleware: InnerRequestLoggingMiddleware
    ) -> None:
        """_get_request_body использует cached body из state (cycle 52 pattern)."""
        middleware.log_body = True  # Enable body logging.
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope("POST", "/path", state={"body": b"cached"}),
            _make_receive(b"ignored"),
            send,
        )

        # Cached body использован.
        assert any(
            "Тело запроса: cached" in str(call)
            for call in middleware.logger.debug.call_args_list
        )

    @pytest.mark.asyncio
    async def test_get_request_body_too_large(
        self, middleware: InnerRequestLoggingMiddleware
    ) -> None:
        """Body > max → placeholder."""
        middleware.log_body = True  # Enable body logging.
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope("POST", "/path", state={"body": b"x" * 2000}),
            _make_receive(b""),
            send,
        )

        # body > max_body_size=1000 → placeholder.
        assert any(
            "слишком велико" in str(call)
            for call in middleware.logger.debug.call_args_list
        )

    @pytest.mark.asyncio
    async def test_capture_response_body(
        self, middleware: InnerRequestLoggingMiddleware
    ) -> None:
        """log_body=True → captures response body chunks через send_wrapper."""
        middleware.log_body = True
        app = AsyncMock()

        async def downstream(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"hello"})

        app.side_effect = downstream
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope("GET", "/path"),
            _make_receive(),
            send,
        )

        # log_body=True → "Тело ответа" в debug log.
        assert any(
            "Тело ответа" in str(call)
            for call in middleware.logger.debug.call_args_list
        )


class TestInnerRequestLoggingMiddlewarePureASGI:
    """Cycle 53: pure ASGI regression-тесты для InnerRequestLoggingMiddleware."""

    @pytest.fixture
    def middleware(self) -> InnerRequestLoggingMiddleware:
        app = AsyncMock()
        mw = InnerRequestLoggingMiddleware(app)
        mw.logger = MagicMock()
        mw.log_body = False
        mw.max_body_size = 1000
        return mw

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(
        self, middleware: InnerRequestLoggingMiddleware
    ) -> None:
        """Non-HTTP scope (websocket) пробрасывается без логирования."""
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

        # websocket.accept прошёл, logger НЕ вызван.
        msgs = [c.args[0] for c in send.await_args_list]
        assert any(m["type"] == "websocket.accept" for m in msgs)
        middleware.logger.info.assert_not_called()

    @pytest.mark.asyncio
    async def test_response_status_captured(
        self, middleware: InnerRequestLoggingMiddleware
    ) -> None:
        """Response status captured через send_wrapper (cycle 53 invariant)."""
        app = AsyncMock()
        app.side_effect = _downstream_ok(status_code=500)
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope("GET", "/path"),
            _make_receive(),
            send,
        )

        # Response log содержит 500.
        assert any(
            "Ответ: 500" in str(call)
            for call in middleware.logger.info.call_args_list
        )

    @pytest.mark.asyncio
    async def test_duration_logged(
        self, middleware: InnerRequestLoggingMiddleware
    ) -> None:
        """Duration в ms logged в response line."""
        app = AsyncMock()

        async def slow_downstream(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        app.side_effect = slow_downstream
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope("GET", "/path"),
            _make_receive(),
            send,
        )

        # Duration в формате "обработан за X.XX мс".
        assert any(
            "обработан за" in str(call)
            for call in middleware.logger.info.call_args_list
        )

    @pytest.mark.asyncio
    async def test_skip_body_logging_when_disabled(
        self, middleware: InnerRequestLoggingMiddleware
    ) -> None:
        """log_body=False → no body logging (ни request, ни response)."""
        middleware.log_body = False
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope("POST", "/path", state={"body": b"any"}),
            _make_receive(),
            send,
        )

        # Нет "Тело запроса" / "Тело ответа" в logs.
        all_logs = " ".join(
            str(call) for call in middleware.logger.debug.call_args_list
        )
        assert "Тело запроса" not in all_logs
        assert "Тело ответа" not in all_logs
