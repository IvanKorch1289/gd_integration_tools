"""Unit tests for ExceptionHandlerMiddleware (cycle 51 pure ASGI)."""


from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.core.errors import BaseError
from src.backend.entrypoints.middlewares.exception_handler import (
    ExceptionHandlerMiddleware,
)


class FakeBaseError(BaseError):
    """Fake BaseError for testing."""

    status_code = 418

    def to_dict(self) -> dict:
        return {"message": "I am a teapot", "hasErrors": True}


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


def _make_scope(
    path: str = "/path",
    state: dict | None = None,
) -> dict:
    return {
        "type": "http",
        "method": "GET",
        "url": f"http://test{path}",
        "path": path,
        "headers": [],
        "query_string": b"",
        **({"state": state} if state is not None else {}),
    }


def _make_receive():
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    return receive


class TestExceptionHandlerMiddleware:
    """Tests for :class:`ExceptionHandlerMiddleware` (cycle 51 pure ASGI)."""

    @pytest.fixture
    def middleware(self) -> ExceptionHandlerMiddleware:
        app = AsyncMock()
        return ExceptionHandlerMiddleware(app)

    @pytest.mark.asyncio
    async def test_no_exception_passes_through(
        self, middleware: ExceptionHandlerMiddleware,
    ) -> None:
        """Normal response от downstream пробрасывается unchanged."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope("/path"),
            _make_receive(),
            send,
        )

        # 200 OK от downstream.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_base_error_handled(
        self, middleware: ExceptionHandlerMiddleware,
    ) -> None:
        """BaseError subclasses → structured response с custom status."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise FakeBaseError(message="boom", status_code=418)

        app.side_effect = downstream
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope("/path"),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 418
        body = _body_message(send)
        parsed = json.loads(body["body"].decode("utf-8"))
        assert "teapot" in parsed["message"]

    @pytest.mark.asyncio
    async def test_generic_error_500(
        self, middleware: ExceptionHandlerMiddleware,
    ) -> None:
        """Generic exceptions → 500 JSON через send (no-raise)."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise RuntimeError("boom")

        app.side_effect = downstream
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope("/path"),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 500
        body = _body_message(send)
        parsed = json.loads(body["body"].decode("utf-8"))
        # Cycle 34 (B-12 fix): новый envelope с error_id (uuid4).
        assert parsed["code"] == "internal_error"
        assert parsed["detail"] == "Internal server error"
        assert "error_id" in parsed

    @pytest.mark.asyncio
    async def test_correlation_and_request_id_injected(
        self, middleware: ExceptionHandlerMiddleware,
    ) -> None:
        """correlation_id и request_id добавляются в error payload."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise ValueError("bad")

        app.side_effect = downstream
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope("/path", state={"correlation_id": "corr-1", "request_id": "req-1"}),
            _make_receive(),
            send,
        )

        body = _body_message(send)
        parsed = json.loads(body["body"].decode("utf-8"))
        assert parsed["correlation_id"] == "corr-1"
        assert parsed["request_id"] == "req-1"

    @pytest.mark.asyncio
    async def test_logs_on_generic_error(
        self, middleware: ExceptionHandlerMiddleware,
    ) -> None:
        """logger.error и logger.exception вызываются для generic exceptions."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise RuntimeError("boom")

        app.side_effect = downstream
        middleware.app = app

        with patch(
            "src.backend.entrypoints.middlewares.exception_handler.logger",
        ) as mock_logger:
            send = AsyncMock()
            await middleware(
                _make_scope("/path"),
                _make_receive(),
                send,
            )

        mock_logger.error.assert_called()
        mock_logger.exception.assert_called()

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(
        self, middleware: ExceptionHandlerMiddleware,
    ) -> None:
        """Non-HTTP scope (websocket) пробрасывается без exception catch."""
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
    async def test_does_not_call_downstream_after_exception(
        self, middleware: ExceptionHandlerMiddleware,
    ) -> None:
        """Cycle 51 invariant: после exception downstream НЕ вызывается повторно.

        Exception уже произошла — повторный call downstream мог бы
        привести к двойной обработке или утечке ресурсов.
        """
        app_call_count = 0

        async def downstream(scope, receive, send):
            nonlocal app_call_count
            app_call_count += 1
            raise RuntimeError("boom")

        app = AsyncMock()
        app.side_effect = downstream
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope("/path"),
            _make_receive(),
            send,
        )

        # downstream вызван только ОДИН раз (до exception).
        assert app_call_count == 1
        # 500 response отправлен.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 500

    @pytest.mark.asyncio
    async def test_websocket_exception_propagates(
        self, middleware: ExceptionHandlerMiddleware,
    ) -> None:
        """Non-HTTP scope exceptions НЕ ловятся (ASGI protocol: пробрасываются)."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise RuntimeError("websocket scope error")

        app.side_effect = downstream
        middleware.app = app

        send = AsyncMock()
        # Должен raise — middleware НЕ ловит exception для non-HTTP.
        with pytest.raises(RuntimeError, match="websocket scope error"):
            await middleware(
                {"type": "websocket", "path": "/ws", "headers": []},
                AsyncMock(),
                send,
            )

    @pytest.mark.asyncio
    async def test_does_not_modify_normal_response(
        self, middleware: ExceptionHandlerMiddleware,
    ) -> None:
        """Cycle 51 invariant: normal response пробрасывается без modification."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 201,
                    "headers": [(b"x-custom", b"value")],
                },
            )
            await send({"type": "http.response.body", "body": b"created"})

        app.side_effect = downstream
        middleware.app = app

        send = AsyncMock()
        await middleware(
            _make_scope("/path"),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 201
        headers = dict(start["headers"])
        assert headers[b"x-custom"] == b"value"
        body = _body_message(send)
        assert body["body"] == b"created"
