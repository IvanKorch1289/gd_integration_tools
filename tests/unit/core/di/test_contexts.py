"""Unit tests for src.backend.core.di.contexts."""

from __future__ import annotations

from src.backend.core.di.contexts import make_dispatch_context
from src.backend.core.interfaces.action_dispatcher import DispatchContext


class TestMakeDispatchContext:
    def test_returns_dispatch_context(self) -> None:
        ctx = make_dispatch_context("http")
        assert isinstance(ctx, DispatchContext)
        assert ctx.source == "http"
        assert ctx.correlation_id is not None
        assert len(ctx.correlation_id) == 32

    def test_uses_provided_correlation_id(self) -> None:
        ctx = make_dispatch_context("ws", correlation_id="abc123")
        assert ctx.correlation_id == "abc123"

    def test_optional_fields(self) -> None:
        ctx = make_dispatch_context(
            "scheduler",
            tenant_id="t1",
            user_id="u1",
            idempotency_key="ik",
            trace_parent="tp",
            attributes={"k": "v"},
        )
        assert ctx.tenant_id == "t1"
        assert ctx.user_id == "u1"
        assert ctx.idempotency_key == "ik"
        assert ctx.trace_parent == "tp"
        assert ctx.attributes == {"k": "v"}

    def test_none_attributes(self) -> None:
        ctx = make_dispatch_context("grpc")
        assert ctx.attributes == {}
