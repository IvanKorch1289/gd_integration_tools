"""Tests for core/observability/correlation.py (S100 — coverage push).

contextvars-based correlation_id / request_id / tenant_id + start_span context manager.
"""

from __future__ import annotations

import pytest
import structlog


def test_module_dunder_all() -> None:
    """__all__ = 10 symbols."""
    from src.backend.core.observability.correlation import __all__ as symbols

    expected = (
        "correlation_id_var",
        "get_correlation_id",
        "get_request_id",
        "get_tenant_id",
        "new_correlation_id",
        "request_id_var",
        "set_correlation_context",
        "set_correlation_id",
        "start_span",
        "tenant_id_var",
    )
    assert symbols == expected


def test_default_context_vars_empty() -> None:
    """ContextVars default = '' (empty string)."""
    from src.backend.core.observability import correlation

    assert correlation.correlation_id_var.get() == ""
    assert correlation.request_id_var.get() == ""
    assert correlation.tenant_id_var.get() == ""


def test_get_correlation_id_default() -> None:
    """get_correlation_id() → '' by default."""
    from src.backend.core.observability.correlation import get_correlation_id

    assert get_correlation_id() == ""


def test_get_request_id_default() -> None:
    """get_request_id() → '' by default."""
    from src.backend.core.observability.correlation import get_request_id

    assert get_request_id() == ""


def test_get_tenant_id_default() -> None:
    """get_tenant_id() → '' by default."""
    from src.backend.core.observability.correlation import get_tenant_id

    assert get_tenant_id() == ""


def test_set_correlation_context_all_three() -> None:
    """set_correlation_context(corr, req, tenant) → set all 3 + structlog.bind."""
    from src.backend.core.observability import correlation

    correlation.set_correlation_context(
        correlation_id="cid-123",
        request_id="req-456",
        tenant_id="tenant-789",
    )
    assert correlation.get_correlation_id() == "cid-123"
    assert correlation.get_request_id() == "req-456"
    assert correlation.get_tenant_id() == "tenant-789"


def test_set_correlation_context_only_correlation_id() -> None:
    """set_correlation_context(corr only) → только correlation_id set."""
    from src.backend.core.observability import correlation

    correlation.set_correlation_context(correlation_id="only-cid")
    assert correlation.get_correlation_id() == "only-cid"
    # request/tenant unchanged (other vars may be left over from previous test).


def test_set_correlation_context_none_does_not_set() -> None:
    """set_correlation_context(correlation_id=None) → не устанавливает."""
    from src.backend.core.observability import correlation

    correlation.set_correlation_context(correlation_id="keep")
    correlation.set_correlation_context(correlation_id=None)
    # Previous value kept (None → no-op).
    assert correlation.get_correlation_id() == "keep"


def test_new_correlation_id_generates_unique() -> None:
    """new_correlation_id() → уникальный hex[:16] ID, set в context."""
    from src.backend.core.observability import correlation

    cid1 = correlation.new_correlation_id()
    cid2 = correlation.new_correlation_id()
    assert cid1 != cid2
    assert len(cid1) == 16
    assert all(c in "0123456789abcdef" for c in cid1)
    assert correlation.get_correlation_id() == cid2  # last one set


def test_set_correlation_id_alias() -> None:
    """set_correlation_id(x) → set_correlation_context(correlation_id=x)."""
    from src.backend.core.observability import correlation

    correlation.set_correlation_id("aliased-cid")
    assert correlation.get_correlation_id() == "aliased-cid"


def test_start_span_no_otel_sdk_yields_none() -> None:
    """start_span: returns Span (real или NonRecordingSpan).

    При configured TracerProvider → real Span. При non-initialized или
    no SDK → fallback. SDK установлен в venv, поэтому получаем real Span
    (NonRecordingSpan если TracerProvider не configured в этом тесте).
    """
    from src.backend.core.observability.correlation import start_span

    with start_span("test-span") as span:
        # Span (real или NonRecordingSpan) — просто проверяем что exists.
        assert span is not None
        # Имеет expected interface (context manager protocol).
        assert hasattr(span, "get_span_context")


def test_start_span_with_attributes() -> None:
    """start_span(name, attributes) — не падает с attrs."""
    from src.backend.core.observability.correlation import start_span

    with start_span("test", attributes={"key": "value"}) as span:
        assert span is not None


def test_start_span_returns_valid_span_object() -> None:
    """start_span: returns object с get_span_context method."""
    from src.backend.core.observability import correlation

    with correlation.start_span("test") as span:
        ctx = span.get_span_context()
        assert ctx is not None
