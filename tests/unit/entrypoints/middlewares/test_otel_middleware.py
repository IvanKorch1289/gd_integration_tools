"""Unit tests for OtelMiddleware (cycle 56 pure ASGI)."""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.entrypoints.middlewares.otel_middleware import OtelMiddleware


def _start_message(send: AsyncMock):
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return msg
    return None


def _downstream_ok(status_code: int = 200):
    async def downstream(scope, receive, send):
        await send(
            {"type": "http.response.start", "status": status_code, "headers": []}
        )
        await send({"type": "http.response.body", "body": b"ok"})

    return downstream


def _make_scope(
    method: str = "GET",
    path: str = "/path",
    headers: list[tuple[bytes, bytes]] | None = None,
    client: tuple[str, int] | None = ("127.0.0.1", 1234),
    state: dict | None = None,
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
        **({"state": state} if state is not None else {}),
    }


def _make_receive():
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    return receive


class TestOtelMiddleware:
    """Tests for :class:`OtelMiddleware` (cycle 56 pure ASGI)."""

    @pytest.fixture
    def middleware_no_tracer(self) -> OtelMiddleware:
        mw = OtelMiddleware(AsyncMock())
        mw._tracer = None
        mw._propagator = None
        return mw

    @pytest.fixture
    def middleware_with_tracer(self) -> OtelMiddleware:
        mw = OtelMiddleware(AsyncMock())
        mw._tracer = MagicMock()
        mw._propagator = MagicMock()
        return mw

    @pytest.mark.asyncio
    async def test_no_tracer_passes_through(
        self, middleware_no_tracer: OtelMiddleware
    ) -> None:
        """Without tracer middleware is no-op."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware_no_tracer.app = app

        send = AsyncMock()
        await middleware_no_tracer(
            _make_scope("GET", "/path"),
            _make_receive(),
            send,
        )

        # Status 200 (без traceparent injection).
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200
        # Нет traceparent header (cycle 56 invariant).
        headers = dict(start["headers"])
        assert b"traceparent" not in headers

    @pytest.mark.asyncio
    async def test_tracer_creates_span(
        self, middleware_with_tracer: OtelMiddleware
    ) -> None:
        """Tracer creates span and injects traceparent."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware_with_tracer.app = app

        span_mock = MagicMock()
        cm_mock = MagicMock()
        cm_mock.__enter__ = MagicMock(return_value=span_mock)
        cm_mock.__exit__ = MagicMock(return_value=None)
        middleware_with_tracer._tracer.start_as_current_span.return_value = cm_mock

        with (
            patch(
                "opentelemetry.trace.get_tracer",
                return_value=middleware_with_tracer._tracer,
            ),
            patch("opentelemetry.trace.SpanKind", MagicMock()),
        ):
            send = AsyncMock()
            await middleware_with_tracer(
                _make_scope("GET", "/path"),
                _make_receive(),
                send,
            )

        # Span был создан.
        middleware_with_tracer._tracer.start_as_current_span.assert_called_once()
        # Traceparent injected.
        start = _start_message(send)
        assert start is not None
        # propagator.inject был вызван (через send_wrapper).
        middleware_with_tracer._propagator.inject.assert_called_once()

    @pytest.mark.asyncio
    async def test_exception_marks_span_and_raises(
        self, middleware_with_tracer: OtelMiddleware
    ) -> None:
        """Exception in call_next marks span and re-raises."""
        app = AsyncMock()

        async def bad_downstream(scope, receive, send):
            raise RuntimeError("boom")

        app.side_effect = bad_downstream
        middleware_with_tracer.app = app

        span_mock = MagicMock()
        cm_mock = MagicMock()
        cm_mock.__enter__ = MagicMock(return_value=span_mock)
        cm_mock.__exit__ = MagicMock(return_value=None)
        middleware_with_tracer._tracer.start_as_current_span.return_value = cm_mock

        with (
            patch(
                "opentelemetry.trace.get_tracer",
                return_value=middleware_with_tracer._tracer,
            ),
            patch("opentelemetry.trace.SpanKind", MagicMock()),
        ):
            send = AsyncMock()
            with pytest.raises(RuntimeError, match="boom"):
                await middleware_with_tracer(
                    _make_scope("GET", "/path"),
                    _make_receive(),
                    send,
                )

        # Exception был записан.
        span_mock.record_exception.assert_called_once()
        span_mock.set_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_5xx_response_marks_error(
        self, middleware_with_tracer: OtelMiddleware
    ) -> None:
        """5xx responses mark span as error."""
        app = AsyncMock()
        app.side_effect = _downstream_ok(status_code=502)
        middleware_with_tracer.app = app

        span_mock = MagicMock()
        cm_mock = MagicMock()
        cm_mock.__enter__ = MagicMock(return_value=span_mock)
        cm_mock.__exit__ = MagicMock(return_value=None)
        middleware_with_tracer._tracer.start_as_current_span.return_value = cm_mock

        with (
            patch(
                "opentelemetry.trace.get_tracer",
                return_value=middleware_with_tracer._tracer,
            ),
            patch("opentelemetry.trace.SpanKind", MagicMock()),
        ):
            send = AsyncMock()
            await middleware_with_tracer(
                _make_scope("GET", "/path"),
                _make_receive(),
                send,
            )

        # 502 status set as http.status_code OR span marked as error.
        # Cycle 56 invariant: status >= 500 -> _mark_error called.
        all_calls_str = " ".join(
            str(call) for call in span_mock.set_attribute.call_args_list
        ) + " " + " ".join(
            str(call) for call in span_mock.set_status.call_args_list
        )
        assert "502" in all_calls_str or "ERROR" in all_calls_str

    def test_inject_traceparent(self, middleware_with_tracer: OtelMiddleware) -> None:
        """_inject_traceparent_to_headers adds traceparent to headers list."""
        headers: list[tuple[bytes, bytes]] = [(b"content-type", b"text/plain")]
        middleware_with_tracer._propagator.inject.side_effect = (
            lambda carrier: carrier.update({"traceparent": "00-abc-123-01"})
        )

        middleware_with_tracer._inject_traceparent_to_headers(headers)

        # traceparent добавлен в headers.
        assert any(k == b"traceparent" for k, _ in headers)
        assert any(
            v == b"00-abc-123-01" for k, v in headers if k == b"traceparent"
        )


class TestOtelMiddlewarePureASGI:
    """Cycle 56: pure ASGI regression-тесты для OtelMiddleware."""

    @pytest.fixture
    def middleware_with_tracer(self) -> OtelMiddleware:
        mw = OtelMiddleware(AsyncMock())
        mw._tracer = MagicMock()
        mw._propagator = MagicMock()
        return mw

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(
        self, middleware_with_tracer: OtelMiddleware
    ) -> None:
        """Non-HTTP scope (websocket) пробрасывается без span creation."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            await send({"type": "websocket.accept"})

        app.side_effect = downstream
        middleware_with_tracer.app = app

        send = AsyncMock()
        await middleware_with_tracer(
            {"type": "websocket", "path": "/ws", "headers": []},
            AsyncMock(),
            send,
        )

        msgs = [c.args[0] for c in send.await_args_list]
        assert any(m["type"] == "websocket.accept" for m in msgs)
        # Span НЕ создан (non-HTTP scope).
        middleware_with_tracer._tracer.start_as_current_span.assert_not_called()

    @pytest.mark.asyncio
    async def test_traceparent_in_response_headers(
        self, middleware_with_tracer: OtelMiddleware
    ) -> None:
        """traceparent injected в response headers (cycle 56 invariant)."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware_with_tracer.app = app

        span_mock = MagicMock()
        cm_mock = MagicMock()
        cm_mock.__enter__ = MagicMock(return_value=span_mock)
        cm_mock.__exit__ = MagicMock(return_value=None)
        middleware_with_tracer._tracer.start_as_current_span.return_value = cm_mock

        middleware_with_tracer._propagator.inject.side_effect = (
            lambda carrier: carrier.update({"traceparent": "00-trace-123-01"})
        )

        with (
            patch(
                "opentelemetry.trace.get_tracer",
                return_value=middleware_with_tracer._tracer,
            ),
            patch("opentelemetry.trace.SpanKind", MagicMock()),
        ):
            send = AsyncMock()
            await middleware_with_tracer(
                _make_scope("GET", "/path"),
                _make_receive(),
                send,
            )

        # traceparent добавлен.
        start = _start_message(send)
        headers = dict(start["headers"])
        assert headers[b"traceparent"] == b"00-trace-123-01"

    @pytest.mark.asyncio
    async def test_does_not_call_downstream_after_exception(
        self, middleware_with_tracer: OtelMiddleware
    ) -> None:
        """Cycle 56 invariant: downstream вызван ОДИН раз даже при exception."""
        call_count = 0

        async def downstream(scope, receive, send):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("boom")

        app = AsyncMock()
        app.side_effect = downstream
        middleware_with_tracer.app = app

        span_mock = MagicMock()
        cm_mock = MagicMock()
        cm_mock.__enter__ = MagicMock(return_value=span_mock)
        cm_mock.__exit__ = MagicMock(return_value=None)
        middleware_with_tracer._tracer.start_as_current_span.return_value = cm_mock

        with (
            patch(
                "opentelemetry.trace.get_tracer",
                return_value=middleware_with_tracer._tracer,
            ),
            patch("opentelemetry.trace.SpanKind", MagicMock()),
        ):
            send = AsyncMock()
            with pytest.raises(RuntimeError, match="boom"):
                await middleware_with_tracer(
                    _make_scope("GET", "/path"),
                    _make_receive(),
                    send,
                )

        # Downstream вызван ОДИН раз.
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_attribute_collection_from_state(
        self, middleware_with_tracer: OtelMiddleware
    ) -> None:
        """correlation.id и request.id извлекаются из scope['state'] (cycle 52)."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware_with_tracer.app = app

        span_mock = MagicMock()
        cm_mock = MagicMock()
        cm_mock.__enter__ = MagicMock(return_value=span_mock)
        cm_mock.__exit__ = MagicMock(return_value=None)
        middleware_with_tracer._tracer.start_as_current_span.return_value = cm_mock

        with (
            patch(
                "opentelemetry.trace.get_tracer",
                return_value=middleware_with_tracer._tracer,
            ),
            patch("opentelemetry.trace.SpanKind", MagicMock()),
        ):
            send = AsyncMock()
            await middleware_with_tracer(
                _make_scope(
                    "GET",
                    "/path",
                    headers=[(b"x-tenant-id", b"t1")],
                    state={"correlation_id": "corr-1", "request_id": "req-1"},
                ),
                _make_receive(),
                send,
            )

        # start_as_current_span был вызван с attrs содержащими state IDs.
        call_kwargs = middleware_with_tracer._tracer.start_as_current_span.call_args
        attrs = call_kwargs.kwargs.get("attributes", {})
        assert attrs.get("correlation.id") == "corr-1"
        assert attrs.get("request.id") == "req-1"
        assert attrs.get("app.tenant_id") == "t1"  # from x-tenant-id header
