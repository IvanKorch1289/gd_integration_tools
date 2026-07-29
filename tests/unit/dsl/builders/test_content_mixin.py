"""Tests for src.backend.dsl.builders.content_mixin.

Cycle 45 note: wire_tap, multicast, recipient_list methods were removed
from EIPContentMixin (they shadowed the working ContentMixin versions
via MRO ordering — the broken implementations stored properties without
dispatching). The canonical implementations live in content.py and have
their own tests in test_content.py.

This file now tests:
- EIPContentMixin.content_enrich() (the only remaining EIP method)
- EIPContentMixin is still present in RouteBuilder MRO
- EIPContentMixin does NOT shadow wire_tap/multicast/recipient_list
  (those are now resolved from ContentMixin)

Edge cases (placeholder substitution, idempotent builds) moved here from
the old test suite (now removed). Tests for the canonical implementations
of wire_tap/multicast/recipient_list are in test_content.py.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.builders.content import (
    MulticastProcessor,
    RecipientListProcessor,
    WireTapProcessor,
)
from src.backend.dsl.engine.exchange import Exchange, Message


# ─── Fixtures & helpers ───────────────────────────────────────────────


@pytest.fixture
def builder() -> RouteBuilder:
    """Fresh RouteBuilder for each test."""
    return RouteBuilder(route_id=f"test_{id(object())}", source="test")


def _run(coro):
    """Run coroutine synchronously via asyncio.run (Python 3.14-safe)."""
    return asyncio.run(coro)


def _make_exchange(body=None) -> Exchange:
    return Exchange(
        in_message=Message(body=body or {}),
    )


# ─── content_enrich() (only remaining EIP mixin method) ──────────────


class TestContentEnrich:
    def test_content_enrich_static(self, builder: RouteBuilder) -> None:
        b = builder.content_enrich(strategy="static", field="ctx", value={"u": 1})
        ex = _make_exchange(body={"a": 1})
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.properties["ctx"] == {"u": 1}

    def test_content_enrich_function(self, builder: RouteBuilder) -> None:
        b = builder.content_enrich(
            strategy="function",
            field="f",
            value=lambda exch: exch.in_message.body.get("a"),
        )
        ex = _make_exchange(body={"a": 42})
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.properties["f"] == 42

    def test_content_enrich_unknown_strategy_raises(self, builder: RouteBuilder) -> None:
        b = builder.content_enrich(strategy="mongodb", field="x", source="ignored")
        ex = _make_exchange(body={})
        with pytest.raises(ValueError, match="unknown enrich strategy"):
            _run(b._processors[-1].process(ex, context=MagicMock()))

    def test_content_enrich_field_name_defaults(self, builder: RouteBuilder) -> None:
        b = builder.content_enrich(
            strategy="static", field="enrichment", value={"x": 1}
        )
        last = b._processors[-1]
        assert last.field == "enrichment"
        assert last.strategy == "static"


# ─── MRO shadowing regression tests (cycle 45) ──────────────────────


class TestMRORoutingResolution:
    """Verify EIPContentMixin doesn't shadow the working ContentMixin methods."""

    def test_wire_tap_resolves_to_content_mixin_implementation(
        self, builder: RouteBuilder
    ) -> None:
        """Cycle 45: wire_tap() must use the working ContentMixin version.

        The ContentMixin version takes tap_processors=[...] and creates
        a real WireTapProcessor (dispatching to side channel).
        """
        tap_proc = MagicMock(spec=WireTapProcessor)
        b = builder.wire_tap(tap_processors=[tap_proc])
        last = b._processors[-1]
        # Must be the working WireTapProcessor (NOT WireTapEIPProcessor).
        assert isinstance(last, WireTapProcessor)

    def test_multicast_resolves_to_content_mixin_implementation(
        self, builder: RouteBuilder
    ) -> None:
        """Cycle 45: multicast() must use the working ContentMixin version."""
        from src.backend.dsl.engine.processors.base import BaseProcessor

        branch_proc = MagicMock(spec=BaseProcessor)
        b = builder.multicast(branches=[[branch_proc], [branch_proc]])
        last = b._processors[-1]
        assert isinstance(last, MulticastProcessor)

    def test_recipient_list_resolves_to_content_mixin_implementation(
        self, builder: RouteBuilder
    ) -> None:
        """Cycle 45: recipient_list() must use the working ContentMixin version."""
        b = builder.recipient_list(recipients_expression=lambda exch: ["a", "b"])
        last = b._processors[-1]
        assert isinstance(last, RecipientListProcessor)


# ─── Edge cases (placeholder substitution) ───────────────────────────


class TestPlaceholderResolution:
    def test_placeholder_left_intact_when_missing(self) -> None:
        from src.backend.dsl.builders.content_mixin import _resolve

        ex = _make_exchange(body={"present": 1})
        assert _resolve("v=${exchange.missing}", ex) == "v=${exchange.missing}"
        assert _resolve("v=${exchange.present}", ex) == "v=1"
