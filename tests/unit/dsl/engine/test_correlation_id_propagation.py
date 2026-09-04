"""S92 M5-#8: tests for correlation_id propagation in DSL Exchange.

Verifies:
- Default UUID4 fallback (when ASGI context unavailable)
- ASGI context propagation (when set via contextvars)
- Independence between Exchange instances (different IDs)
"""

from __future__ import annotations

import re
import uuid

from src.backend.dsl.engine.exchange import Exchange, _make_correlation_id

UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


class TestCorrelationIdFallback:
    """S92 M5-#8: fallback to UUID4 when ASGI context unavailable."""

    def test_fallback_returns_valid_uuid4(self) -> None:
        """No ASGI context → UUID4."""
        cid = _make_correlation_id()
        assert UUID4_RE.match(cid), f"Expected UUID4, got {cid!r}"

    def test_fallback_each_call_unique(self) -> None:
        """Each call returns a new UUID (no caching)."""
        cids = {_make_correlation_id() for _ in range(100)}
        assert len(cids) == 100  # All unique

    def test_fallback_returns_uuid_object_string(self) -> None:
        """Type is str (UUID4 stringified)."""
        cid = _make_correlation_id()
        assert isinstance(cid, str)
        # Parseable as UUID
        uuid.UUID(cid)  # raises ValueError if not valid


class TestExchangeCorrelationId:
    """S92 M5-#8: Exchange.correlation_id uses factory."""

    def test_new_exchange_has_uuid4_by_default(self) -> None:
        """Fresh Exchange → correlation_id is UUID4 (no ASGI context)."""
        ex = Exchange()
        assert UUID4_RE.match(ex.meta.correlation_id)

    def test_two_exchanges_have_different_ids(self) -> None:
        """Different Exchanges → different correlation_ids (no global state)."""
        ex1 = Exchange()
        ex2 = Exchange()
        assert ex1.meta.correlation_id != ex2.meta.correlation_id


class TestCorrelationIdWithAsgiContext:
    """S92 M5-#8: asgi_correlation_id context propagation."""

    def test_asgi_context_propagates(self) -> None:
        """When asgi_correlation_id context is set, factory returns its value."""
        try:
            from asgi_correlation_id import CorrelationIdMiddleware
        except ImportError:
            import pytest

            pytest.skip("asgi_correlation_id not installed")

        # Use raw contextvars (avoids Starlette deprecation + API mismatch)
        from asgi_correlation_id.context import correlation_id

        token = correlation_id.set("test-12345")
        try:
            cid = _make_correlation_id()
            assert cid == "test-12345", f"Expected 'test-12345', got {cid!r}"
        finally:
            correlation_id.reset(token)
