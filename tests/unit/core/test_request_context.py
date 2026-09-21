"""Tests for src.backend.core.request_context."""

from __future__ import annotations

from src.backend.core.request_context import (
    RequestContext,
    bind_request_context,
    clear_request_context,
)


class TestRequestContext:
    def test_current_returns_none_by_default(self) -> None:
        assert RequestContext.current() is None

    def test_bind_and_clear(self) -> None:
        ctx = RequestContext(
            correlation_id="c1", request_id="r1", method="GET", path="/"
        )
        token = bind_request_context(ctx)
        assert RequestContext.current() is ctx
        clear_request_context(token)
        assert RequestContext.current() is None

    def test_fields(self) -> None:
        ctx = RequestContext(
            correlation_id="c1",
            request_id="r1",
            method="POST",
            path="/api",
            tenant_id="t1",
            client_id="client1",
        )
        assert ctx.correlation_id == "c1"
        assert ctx.tenant_id == "t1"
        assert ctx.trace_id is None
        assert ctx.auth is None
