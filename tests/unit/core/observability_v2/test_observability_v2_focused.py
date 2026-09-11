"""Focused tests for ``core.observability_v2`` (Wave 1 P0 #52)."""

from __future__ import annotations

import asyncio

import pytest

from src.backend.core.observability_v2 import (
    CorrelationPropagator,
    SemanticContext,
    TraceContextCarrier,
    get_current_context,
    reset_current_context,
    set_current_context,
)


class TestSemanticContextInit:
    def test_defaults(self) -> None:
        c = SemanticContext()
        assert c.trace_id == ""
        assert c.span_id == ""
        assert c.correlation_id == ""
        assert c.business_keys == {}
        assert c.tenant_id == ""
        assert c.route_id == ""
        assert c.user_id == ""
        assert c.session_id == ""
        assert c.parent_span_id == ""
        assert c.attributes == {}

    def test_full(self) -> None:
        c = SemanticContext(
            trace_id="abc",
            span_id="def",
            correlation_id="cid",
            business_keys={"order_id": "o1"},
            tenant_id="t1",
            route_id="r1",
            user_id="u1",
            session_id="s1",
            parent_span_id="p1",
            attributes={"x": 1},
        )
        assert c.business_keys == {"order_id": "o1"}
        assert c.attributes == {"x": 1}


class TestSemanticContextNewRoot:
    def test_new_root_generates_ids(self) -> None:
        c = SemanticContext.new_root()
        assert len(c.trace_id) == 32  # W3C trace-id format
        assert len(c.span_id) == 16  # W3C span-id format
        assert c.correlation_id  # UUID
        assert c.parent_span_id == ""

    def test_new_root_with_correlation_id(self) -> None:
        c = SemanticContext.new_root(correlation_id="my-cid")
        assert c.correlation_id == "my-cid"

    def test_new_root_unique(self) -> None:
        c1 = SemanticContext.new_root()
        c2 = SemanticContext.new_root()
        assert c1.trace_id != c2.trace_id


class TestSemanticContextNewChild:
    def test_new_child_inherits_trace(self) -> None:
        parent = SemanticContext.new_root()
        parent.business_keys["order_id"] = "o1"
        parent.tenant_id = "t1"
        child = SemanticContext.new_child(parent)
        assert child.trace_id == parent.trace_id
        assert child.span_id != parent.span_id
        assert child.parent_span_id == parent.span_id
        assert child.business_keys == {"order_id": "o1"}
        assert child.tenant_id == "t1"

    def test_new_child_copy_not_reference(self) -> None:
        """Child business_keys copy (не reference)."""
        parent = SemanticContext.new_root()
        parent.business_keys["k"] = "v1"
        child = SemanticContext.new_child(parent)
        child.business_keys["k"] = "v2"
        assert parent.business_keys["k"] == "v1"
        assert child.business_keys["k"] == "v2"


class TestSemanticContextMutators:
    def test_set_business_key(self) -> None:
        c = SemanticContext()
        c.set_business_key("order_id", "o1")
        assert c.business_keys == {"order_id": "o1"}

    def test_set_attribute(self) -> None:
        c = SemanticContext()
        c.set_attribute("custom", 42)
        assert c.attributes == {"custom": 42}


class TestSemanticContextSerialization:
    def test_to_dict(self) -> None:
        c = SemanticContext(
            trace_id="abc",
            span_id="def",
            correlation_id="cid",
            business_keys={"order_id": "o1"},
            tenant_id="t1",
        )
        d = c.to_dict()
        assert d["trace_id"] == "abc"
        assert d["business_keys"] == {"order_id": "o1"}

    def test_from_dict(self) -> None:
        d = {
            "trace_id": "abc",
            "span_id": "def",
            "correlation_id": "cid",
            "business_keys": {"order_id": "o1"},
            "tenant_id": "t1",
        }
        c = SemanticContext.from_dict(d)
        assert c.trace_id == "abc"
        assert c.business_keys == {"order_id": "o1"}

    def test_roundtrip(self) -> None:
        original = SemanticContext.new_root()
        original.business_keys["order_id"] = "o1"
        restored = SemanticContext.from_dict(original.to_dict())
        assert restored.trace_id == original.trace_id
        assert restored.business_keys == original.business_keys


class TestContextVars:
    def test_get_current_default_none(self) -> None:
        assert get_current_context() is None

    def test_set_and_get(self) -> None:
        c = SemanticContext(correlation_id="cid")
        token = set_current_context(c)
        try:
            assert get_current_context() is c
        finally:
            reset_current_context(token)
        assert get_current_context() is None

    def test_set_none(self) -> None:
        c = SemanticContext(correlation_id="cid")
        token = set_current_context(c)
        try:
            assert get_current_context() is c
        finally:
            reset_current_context(token)
        # Set to None.
        token2 = set_current_context(None)
        assert get_current_context() is None
        reset_current_context(token2)


class TestAsyncIsolation:
    async def test_async_isolation(self) -> None:
        """Context isolated между concurrent tasks (через contextvars)."""
        c1 = SemanticContext(correlation_id="cid-1")
        c2 = SemanticContext(correlation_id="cid-2")

        async def task(token_cid: str, expected: str) -> str:
            c = SemanticContext(correlation_id=token_cid)
            token = set_current_context(c)
            try:
                await asyncio.sleep(0.01)
                return get_current_context().correlation_id
            finally:
                reset_current_context(token)

        results = await asyncio.gather(
            task("cid-1", "cid-1"),
            task("cid-2", "cid-2"),
        )
        assert results == ["cid-1", "cid-2"]


class TestTraceContextCarrierInject:
    def test_inject_full(self) -> None:
        c = SemanticContext(
            trace_id="abcdef" + "0" * 26,  # 32 hex
            span_id="1234" + "0" * 12,  # 16 hex
            correlation_id="cid",
            tenant_id="t1",
            route_id="r1",
            business_keys={"order_id": "o1", "file_id": "f1"},
        )
        headers = TraceContextCarrier.inject(c)
        assert "traceparent" in headers
        assert headers[TraceContextCarrier.CORRELATION_ID_HEADER] == "cid"
        assert headers[TraceContextCarrier.TENANT_ID_HEADER] == "t1"
        assert headers[TraceContextCarrier.ROUTE_ID_HEADER] == "r1"
        # Business keys comma-separated.
        keys = headers[TraceContextCarrier.BUSINESS_KEYS_HEADER]
        assert "order_id=o1" in keys
        assert "file_id=f1" in keys

    def test_inject_minimal(self) -> None:
        """Пустой context → пустые headers."""
        c = SemanticContext()
        headers = TraceContextCarrier.inject(c)
        assert headers == {}


class TestTraceContextCarrierExtract:
    def test_extract_full(self) -> None:
        headers = {
            "traceparent": "00-abcdef00000000000000000000000000-1234000000000000-01",
            "X-Correlation-ID": "cid",
            "X-Tenant-ID": "t1",
            "X-Route-ID": "r1",
            "X-Business-Keys": "order_id=o1,file_id=f1",
        }
        c = TraceContextCarrier.extract(headers)
        assert c.trace_id == "abcdef00000000000000000000000000"
        assert c.span_id == "1234000000000000"
        assert c.correlation_id == "cid"
        assert c.tenant_id == "t1"
        assert c.route_id == "r1"
        assert c.business_keys == {"order_id": "o1", "file_id": "f1"}

    def test_extract_empty(self) -> None:
        c = TraceContextCarrier.extract({})
        assert c.trace_id == ""
        assert c.business_keys == {}

    def test_extract_partial(self) -> None:
        headers = {"X-Correlation-ID": "cid"}
        c = TraceContextCarrier.extract(headers)
        assert c.correlation_id == "cid"
        assert c.trace_id == ""

    def test_extract_malformed_traceparent(self) -> None:
        """Malformed traceparent → empty trace_id/span_id (no crash)."""
        headers = {"traceparent": "garbage"}
        c = TraceContextCarrier.extract(headers)
        assert c.trace_id == ""

    def test_roundtrip(self) -> None:
        original = SemanticContext.new_root()
        original.business_keys["order_id"] = "o1"
        original.tenant_id = "t1"
        headers = TraceContextCarrier.inject(original)
        restored = TraceContextCarrier.extract(headers)
        assert restored.trace_id == original.trace_id
        assert restored.span_id == original.span_id
        assert restored.correlation_id == original.correlation_id
        assert restored.tenant_id == original.tenant_id
        assert restored.business_keys == original.business_keys


class TestCorrelationPropagator:
    def test_inject_to_headers_alias(self) -> None:
        c = SemanticContext(correlation_id="cid")
        headers = CorrelationPropagator.inject_to_headers(c)
        assert "X-Correlation-ID" in headers

    def test_extract_from_headers_alias(self) -> None:
        headers = {"X-Correlation-ID": "cid"}
        c = CorrelationPropagator.extract_from_headers(headers)
        assert c.correlation_id == "cid"

    def test_inject_to_metadata(self) -> None:
        c = SemanticContext(correlation_id="cid", business_keys={"k": "v"})
        meta = CorrelationPropagator.inject_to_metadata(c)
        assert meta["correlation_id"] == "cid"
        assert meta["business_keys"] == {"k": "v"}

    def test_extract_from_metadata(self) -> None:
        meta = {"correlation_id": "cid", "business_keys": {"k": "v"}}
        c = CorrelationPropagator.extract_from_metadata(meta)
        assert c.correlation_id == "cid"
        assert c.business_keys == {"k": "v"}

    def test_extract_from_empty_metadata(self) -> None:
        c = CorrelationPropagator.extract_from_metadata({})
        assert c.trace_id == ""


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import observability_v2

        assert len(observability_v2.__all__) == 6


class TestRealisticExample:
    def test_full_lifecycle_http(self) -> None:
        """Realistic: HTTP request → downstream call → response."""
        # 1. Receive incoming request with headers.
        incoming = {
            "traceparent": "00-abc12300000000000000000000000000-def4560000000000-01",
            "X-Correlation-ID": "trace-abc",
            "X-Tenant-ID": "tenant-1",
            "X-Route-ID": "order-create",
            "X-Business-Keys": "order_id=o1,customer_id=c1",
        }

        # 2. Extract context.
        ctx = TraceContextCarrier.extract(incoming)
        assert ctx.correlation_id == "trace-abc"
        assert ctx.business_keys["order_id"] == "o1"

        # 3. Make it current + create child span.
        token = set_current_context(ctx)
        try:
            child = SemanticContext.new_child(get_current_context())
            child.set_attribute("db.query", "INSERT INTO orders ...")

            # 4. Forward to downstream (MQ).
            mq_metadata = CorrelationPropagator.inject_to_metadata(child)
            # Verify downstream can extract it.
            downstream = CorrelationPropagator.extract_from_metadata(mq_metadata)
            assert downstream.trace_id == ctx.trace_id
            assert downstream.correlation_id == "trace-abc"
            assert downstream.business_keys["order_id"] == "o1"
            assert downstream.attributes["db.query"] == "INSERT INTO orders ..."
        finally:
            reset_current_context(token)
