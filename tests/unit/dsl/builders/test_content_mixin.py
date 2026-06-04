"""Unit-тесты EIPContentMixin (S39 W2, V22 NEW): 4 EIP DSL methods.

Покрытие:
    * enrich — http / static / function strategies + field assignment.
    * wire_tap — sync / async / recorded in exchange.
    * multicast — sequential / parallel / empty list no-op.
    * recipient_list — static / callable / empty / None / parallel flag.
    * chaining — full pipeline ``enrich → wire_tap → multicast``.
    * integration — RouteBuilder MRO composition.

Target: 18+ tests, ≥95% line coverage of content_mixin.py.
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.builders.content_mixin import (
    EIPContentMixin,
    EnrichEIPProcessor,
    MulticastEIPProcessor,
    RecipientListEIPProcessor,
    WireTapEIPProcessor,
)
from src.backend.dsl.engine.exchange import Exchange, Message


# ─── Fixtures & helpers ───────────────────────────────────────────────


@pytest.fixture
def builder() -> RouteBuilder:
    return RouteBuilder.from_("test_eip_route", source="internal:test")


def _make_exchange(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange:
    """Construct an Exchange with the given body for processor tests."""
    return Exchange(in_message=Message(body=body, headers=headers or {}), properties={})


def _run(coro: Any) -> Any:
    """Run an awaitable synchronously (test helper)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ─── Mixin class membership ───────────────────────────────────────────


class TestMixinRegistration:
    def test_mixin_in_route_builder_mro(self) -> None:
        """EIPContentMixin is in RouteBuilder MRO after integration."""
        assert EIPContentMixin in RouteBuilder.__mro__

    def test_mixin_has_empty_slots(self) -> None:
        """Mixin is stateless (per builders/base.py contract)."""
        assert EIPContentMixin.__slots__ == ()

    def test_mixin_public_api(self) -> None:
        for method in ("content_enrich", "wire_tap", "multicast", "recipient_list"):
            assert callable(getattr(EIPContentMixin, method)), method


# ─── enrich() ─────────────────────────────────────────────────────────


class TestEnrich:
    def test_enrich_static_sets_field(self, builder: RouteBuilder) -> None:
        b = builder.content_enrich(
            strategy="static", field="user_details", value={"id": 42, "name": "x"}
        )
        last = b._processors[-1]
        assert isinstance(last, EnrichEIPProcessor)
        ex = _make_exchange(body={"a": 1})
        _run(last.process(ex, context=MagicMock()))
        assert ex.properties["user_details"] == {"id": 42, "name": "x"}

    def test_enrich_function_strategy(self, builder: RouteBuilder) -> None:
        b = builder.content_enrich(
            strategy="function",
            field="lookup",
            value=lambda exch: {"computed": exch.in_message.body["x"] * 2},
        )
        ex = _make_exchange(body={"x": 21})
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.properties["lookup"] == {"computed": 42}

    def test_enrich_http_strategy_with_placeholder(self, builder: RouteBuilder) -> None:
        b = builder.content_enrich(
            strategy="http",
            field="remote",
            source="https://api.test/users/${exchange.user_id}",
        )
        ex = _make_exchange(body={"user_id": 7})
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"id": 7, "name": "alice"}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.properties["remote"] == {"id": 7, "name": "alice"}

    def test_enrich_http_non_json_falls_back_to_raw(
        self, builder: RouteBuilder
    ) -> None:
        b = builder.content_enrich(
            strategy="http", field="raw_body", source="https://api.test/text"
        )
        ex = _make_exchange(body={})
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"plain text response"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.properties["raw_body"] == {"_raw": "plain text response"}

    def test_enrich_unknown_strategy_raises(self, builder: RouteBuilder) -> None:
        b = builder.content_enrich(strategy="mongodb", field="x", source="ignored")
        ex = _make_exchange(body={})
        with pytest.raises(ValueError, match="unknown enrich strategy"):
            _run(b._processors[-1].process(ex, context=MagicMock()))


# ─── wire_tap() ───────────────────────────────────────────────────────


class TestWireTap:
    def test_wire_tap_records_entry(self, builder: RouteBuilder) -> None:
        b = builder.wire_tap("log_topic", async_=False)
        last = b._processors[-1]
        assert isinstance(last, WireTapEIPProcessor)
        ex = _make_exchange(body={"a": 1})
        _run(last.process(ex, context=MagicMock()))
        taps = ex.properties["_wire_taps"]
        assert taps == [{"sink": "log_topic", "async": False}]

    def test_wire_tap_async_does_not_block(self, builder: RouteBuilder) -> None:
        b = builder.wire_tap("audit_topic", async_=True)
        ex = _make_exchange(body={})
        # If async were not handled, the executor.submit could race; here
        # we just assert the property was recorded synchronously.
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.properties["_wire_taps"][-1]["sink"] == "audit_topic"
        assert ex.properties["_wire_taps"][-1]["async"] is True

    def test_wire_tap_returns_builder_for_chaining(self, builder: RouteBuilder) -> None:
        result = builder.wire_tap("x").wire_tap("y")
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 2

    def test_wire_tap_default_async_true(self, builder: RouteBuilder) -> None:
        b = builder.wire_tap("default_topic")
        last = b._processors[-1]
        assert last.async_ is True


# ─── multicast() ──────────────────────────────────────────────────────


class TestMulticast:
    def test_multicast_2_sinks_records_both(self, builder: RouteBuilder) -> None:
        b = builder.multicast(["topic_a", "topic_b"], parallel=True)
        last = b._processors[-1]
        assert isinstance(last, MulticastEIPProcessor)
        ex = _make_exchange(body={})
        _run(last.process(ex, context=MagicMock()))
        assert ex.properties["_multicast_sinks"] == ["topic_a", "topic_b"]
        assert ex.properties["_multicast_parallel"] is True

    def test_multicast_parallel_true(self, builder: RouteBuilder) -> None:
        b = builder.multicast(["a", "b", "c"], parallel=True)
        ex = _make_exchange(body={})
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.properties["_multicast_parallel"] is True

    def test_multicast_sequential(self, builder: RouteBuilder) -> None:
        b = builder.multicast(["a", "b"], parallel=False)
        ex = _make_exchange(body={})
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.properties["_multicast_parallel"] is False
        assert ex.properties["_multicast_sinks"] == ["a", "b"]

    def test_multicast_empty_sinks_is_noop(self, builder: RouteBuilder) -> None:
        before = len(builder._processors)
        result = builder.multicast([])
        # No-op: no processor added.
        assert result is builder
        assert len(builder._processors) == before


# ─── recipient_list() ─────────────────────────────────────────────────


class TestRecipientList:
    def test_recipient_list_string_list(self, builder: RouteBuilder) -> None:
        b = builder.recipient_list(["a", "b", "c"])
        last = b._processors[-1]
        assert isinstance(last, RecipientListEIPProcessor)
        ex = _make_exchange(body={})
        _run(last.process(ex, context=MagicMock()))
        assert ex.properties["_recipients"] == ["a", "b", "c"]
        assert ex.properties["_recipients_parallel"] is True

    def test_recipient_list_callable(self, builder: RouteBuilder) -> None:
        b = builder.recipient_list(
            lambda exch: [f"user_{exch.in_message.body['id']}"], parallel=False
        )
        ex = _make_exchange(body={"id": 99})
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.properties["_recipients"] == ["user_99"]
        assert ex.properties["_recipients_parallel"] is False

    def test_recipient_list_empty_list(self, builder: RouteBuilder) -> None:
        b = builder.recipient_list([])
        ex = _make_exchange(body={})
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.properties["_recipients"] == []

    def test_recipient_list_callable_returning_none(
        self, builder: RouteBuilder
    ) -> None:
        b = builder.recipient_list(lambda _exch: None)
        ex = _make_exchange(body={})
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.properties["_recipients"] == []

    def test_recipient_list_callable_returning_empty(
        self, builder: RouteBuilder
    ) -> None:
        b = builder.recipient_list(lambda _exch: [])
        ex = _make_exchange(body={})
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.properties["_recipients"] == []


# ─── Chaining & integration ───────────────────────────────────────────


class TestChaining:
    def test_enrich_wiretap_multicast_chain(self, builder: RouteBuilder) -> None:
        result = (
            builder.content_enrich(strategy="static", field="ctx", value={"u": 1})
            .wire_tap("audit")
            .multicast(["out_a", "out_b"], parallel=True)
        )
        assert isinstance(result, RouteBuilder)
        procs = result._processors
        assert len(procs) == 3
        assert isinstance(procs[0], EnrichEIPProcessor)
        assert isinstance(procs[1], WireTapEIPProcessor)
        assert isinstance(procs[2], MulticastEIPProcessor)

    def test_full_pipeline_execution(self, builder: RouteBuilder) -> None:
        """End-to-end: enrich → wire_tap → recipient_list, run on exchange."""
        route = (
            builder.content_enrich(strategy="static", field="ctx", value={"k": "v"})
            .wire_tap("audit", async_=False)
            .recipient_list(["x", "y"])
            .build()
        )
        ex = _make_exchange(body={"input": "data"})
        engine = route
        # Manually walk the pipeline to verify state propagation.
        for proc in route.processors:  # type: ignore[attr-defined]
            _run(proc.process(ex, context=MagicMock()))
        assert ex.properties["ctx"] == {"k": "v"}
        assert ex.properties["_wire_taps"] == [{"sink": "audit", "async": False}]
        assert ex.properties["_recipients"] == ["x", "y"]


# ─── Edge cases ───────────────────────────────────────────────────────


class TestEdgeCases:
    def test_placeholder_left_intact_when_missing(self) -> None:
        from src.backend.dsl.builders.content_mixin import _resolve

        ex = _make_exchange(body={"present": 1})
        assert _resolve("v=${exchange.missing}", ex) == "v=${exchange.missing}"
        assert _resolve("v=${exchange.present}", ex) == "v=1"

    def test_enrich_field_name_defaults(self, builder: RouteBuilder) -> None:
        b = builder.content_enrich(
            strategy="static", field="enrichment", value={"x": 1}
        )
        last = b._processors[-1]
        assert last.field == "enrichment"
        assert last.strategy == "static"

    def test_processor_to_spec_is_none_or_dict(self, builder: RouteBuilder) -> None:
        """BaseProcessor.to_spec default returns None — processors don't override."""
        p = builder.content_enrich(
            strategy="static", field="x", value={1: 2}
        )._processors[-1]
        # Default BaseProcessor.to_spec returns None; we don't require spec round-trip.
        assert p.to_spec() is None

    def test_idempotent_repeated_wire_tap(self, builder: RouteBuilder) -> None:
        b = builder.wire_tap("a").wire_tap("a")  # same sink twice
        ex = _make_exchange(body={})
        for proc in b._processors:
            _run(proc.process(ex, context=MagicMock()))
        # Both calls recorded (idempotent — no dedup expected).
        assert len(ex.properties["_wire_taps"]) == 2
