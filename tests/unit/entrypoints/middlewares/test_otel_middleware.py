"""Unit tests for OtelMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request, Response

from src.backend.entrypoints.middlewares.otel_middleware import OtelMiddleware


class TestOtelMiddleware:
    """Tests for :class:`OtelMiddleware`."""

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
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/path",
                "path": "/path",
                "headers": [(b"host", b"test")],
            }
        )
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        result = await middleware_no_tracer.dispatch(request, call_next)

        assert result is response
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_tracer_creates_span(
        self, middleware_with_tracer: OtelMiddleware
    ) -> None:
        """Tracer creates span and sets attributes."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/path",
                "path": "/path",
                "headers": [(b"host", b"test"), (b"user-agent", b"ua")],
                "client": ("127.0.0.1", 1234),
            }
        )
        response = Response(content=b"ok", status_code=200)
        call_next = AsyncMock(return_value=response)

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
            result = await middleware_with_tracer.dispatch(request, call_next)

        assert result is response
        middleware_with_tracer._tracer.start_as_current_span.assert_called_once()
        span_mock.set_attribute.assert_called()

    @pytest.mark.asyncio
    async def test_exception_marks_span_and_raises(
        self, middleware_with_tracer: OtelMiddleware
    ) -> None:
        """Exception in call_next marks span and re-raises."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/path",
                "path": "/path",
                "headers": [(b"host", b"test")],
            }
        )
        call_next = AsyncMock(side_effect=RuntimeError("boom"))

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
            with pytest.raises(RuntimeError, match="boom"):
                await middleware_with_tracer.dispatch(request, call_next)

        span_mock.record_exception.assert_called_once()
        span_mock.set_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_5xx_response_marks_error(
        self, middleware_with_tracer: OtelMiddleware
    ) -> None:
        """5xx responses mark span as error."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/path",
                "path": "/path",
                "headers": [(b"host", b"test")],
            }
        )
        response = Response(content=b"err", status_code=502)
        call_next = AsyncMock(return_value=response)

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
            result = await middleware_with_tracer.dispatch(request, call_next)

        assert result is response
        span_mock.set_attribute.assert_any_call("http.status_code", 502)

    def test_extract_context_with_propagator(
        self, middleware_with_tracer: OtelMiddleware
    ) -> None:
        """_extract_context delegates to propagator."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/path",
                "path": "/path",
                "headers": [(b"traceparent", b"00-abc-123-01")],
            }
        )
        middleware_with_tracer._propagator.extract.return_value = {"span": 1}

        ctx = middleware_with_tracer._extract_context(request)

        assert ctx == {"span": 1}
        middleware_with_tracer._propagator.extract.assert_called_once()

    def test_extract_context_no_propagator(
        self, middleware_no_tracer: OtelMiddleware
    ) -> None:
        """_extract_context returns None without propagator."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/path",
                "path": "/path",
                "headers": [],
            }
        )
        assert middleware_no_tracer._extract_context(request) is None

    def test_inject_traceparent(self, middleware_with_tracer: OtelMiddleware) -> None:
        """_inject_traceparent adds headers to response."""
        response = Response(content=b"ok")
        middleware_with_tracer._propagator.inject.side_effect = lambda carrier: (
            carrier.update({"traceparent": "00-abc-123-01"})
        )

        middleware_with_tracer._inject_traceparent(response)

        assert response.headers["traceparent"] == "00-abc-123-01"

    def test_build_attributes_basic(
        self, middleware_with_tracer: OtelMiddleware
    ) -> None:
        """_build_attributes collects HTTP attributes."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/api?q=1",
                "path": "/api",
                "headers": [(b"user-agent", b"pytest")],
                "client": ("10.0.0.1", 1234),
            }
        )
        attrs = OtelMiddleware._build_attributes(request)

        assert attrs["http.method"] == "POST"
        assert attrs["http.route"] == "/api"
        assert attrs["http.client_ip"] == "10.0.0.1"
        assert attrs["http.user_agent"] == "pytest"

    def test_build_attributes_with_state_ids(
        self, middleware_with_tracer: OtelMiddleware
    ) -> None:
        """_build_attributes includes correlation/request id from state."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/path",
                "path": "/path",
                "headers": [],
                "client": ("127.0.0.1", 1234),
            }
        )
        request.state.correlation_id = "corr-1"
        request.state.request_id = "req-1"

        attrs = OtelMiddleware._build_attributes(request)

        assert attrs["correlation.id"] == "corr-1"
        assert attrs["request.id"] == "req-1"

    def test_build_attributes_tenant_header(
        self, middleware_with_tracer: OtelMiddleware
    ) -> None:
        """_build_attributes reads tenant from header."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/path",
                "path": "/path",
                "headers": [(b"x-tenant-id", b"t1")],
            }
        )
        attrs = OtelMiddleware._build_attributes(request)
        assert attrs["app.tenant_id"] == "t1"

    def test_build_attributes_tenant_from_contextvar(
        self, middleware_with_tracer: OtelMiddleware
    ) -> None:
        """_build_attributes falls back to contextvar tenant."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/path",
                "path": "/path",
                "headers": [],
            }
        )
        fake_ctx = MagicMock()
        fake_ctx.tenant_id = "ctx-tenant"

        with patch("src.backend.core.tenancy.current_tenant", return_value=fake_ctx):
            attrs = OtelMiddleware._build_attributes(request)

        assert attrs["app.tenant_id"] == "ctx-tenant"

    def test_mark_error(self, middleware_with_tracer: OtelMiddleware) -> None:
        """_mark_error sets status and records exception."""
        span = MagicMock()
        exc = RuntimeError("fail")

        with (
            patch("opentelemetry.trace.Status"),
            patch("opentelemetry.trace.StatusCode"),
        ):
            OtelMiddleware._mark_error(span, exc)

        span.set_status.assert_called_once()
        span.record_exception.assert_called_once_with(exc)
