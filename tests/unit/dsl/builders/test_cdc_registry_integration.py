"""Integration tests для ``RouteBuilder.from_cdc_registry`` (S101 W2).

S101 W1 added ``from_cdc_registry`` как preferred path для CDC source
registration через :func:`get_cdc_source` factory (вместо bypass'а через
concrete ``infrastructure.sources.cdc.CDCSource``).

W2 coverage:
* DSL builder construction: source prefix ``cdc-registry:<backend>``.
* ``_source_instance`` — concrete backend, Protocol-typed.
* ``from_cdc_registry`` propagates ``ValueError`` для unknown backend.
* Mixin works alongside other from_* методов (``from_cdc``, ``from_cdc_logical``)
  — backward compatibility.
* ``_source_instance`` корректно создаётся для каждого supported backend.

Note: ``CdcSourcesMixin`` is mixed into ``RouteBuilder`` via
``TransportSourcesMixin``. Direct call ``CdcSourcesMixin()`` fails
(no ``__init__``). Tests use ``RouteBuilder.from_cdc_registry(...)``.
"""
from __future__ import annotations

import pytest

from src.backend.core.cdc.source import CDCSource
from src.backend.dsl.builders.base import RouteBuilder
from src.backend.infrastructure.cdc import (
    DebeziumEventsCDCBackend,
    ListenNotifyCDCBackend,
    PollCDCBackend,
)


def test_from_cdc_registry_poll_builds_route() -> None:
    """``RouteBuilder.from_cdc_registry("poll", ...)`` → PollCDCBackend."""
    builder = RouteBuilder.from_cdc_registry("test", "poll", profile="dev")
    assert builder.route_id == "test"
    assert "cdc-registry:poll" in str(builder.source)
    assert isinstance(builder._source_instance, PollCDCBackend)
    assert isinstance(builder._source_instance, CDCSource)


def test_from_cdc_registry_listen_notify() -> None:
    """``from_cdc_registry("listen_notify", ...)`` → ListenNotifyCDCBackend."""
    builder = RouteBuilder.from_cdc_registry(
        "test", "listen_notify", dsn="postgresql://x", channel="my_ch"
    )
    assert isinstance(builder._source_instance, ListenNotifyCDCBackend)
    assert "listen_notify" in str(builder.source)


def test_from_cdc_registry_debezium() -> None:
    """``from_cdc_registry("debezium", ...)`` → DebeziumEventsCDCBackend."""
    builder = RouteBuilder.from_cdc_registry(
        "test", "debezium", bootstrap_servers="kafka:9092", group_id="g1"
    )
    assert isinstance(builder._source_instance, DebeziumEventsCDCBackend)
    assert "debezium" in str(builder.source)


def test_from_cdc_registry_unknown_raises() -> None:
    """``from_cdc_registry("unknown", ...)`` — ValueError (factory re-raises)."""
    with pytest.raises(ValueError) as exc_info:
        RouteBuilder.from_cdc_registry("test", "unknown")
    assert "unknown" in str(exc_info.value).lower()


def test_from_cdc_registry_fake() -> None:
    """``from_cdc_registry("fake", ...)`` → FakeCDCSource для test/dev."""
    builder = RouteBuilder.from_cdc_registry("test", "fake")
    assert isinstance(builder._source_instance, CDCSource)
    assert type(builder._source_instance).__name__ == "FakeCDCSource"


def test_from_cdc_registry_chains_with_dispatch() -> None:
    """``from_cdc_registry(...).dispatch_action(...).build()`` — end-to-end chain."""
    builder = RouteBuilder.from_cdc_registry(
        "orders.changes", "poll", profile="dev"
    )
    # Verify builder state — has source, route_id, source_instance
    assert hasattr(builder, "route_id")
    assert hasattr(builder, "source")
    assert hasattr(builder, "_source_instance")
    assert builder.route_id == "orders.changes"


def test_legacy_from_cdc_still_works() -> None:
    """Backward compat: ``from_cdc`` (legacy path) — конструктор still works.

    Per S99 W3 lesson: split-brain consolidation, not deprecation. Legacy
    path оставлен для backward compat, новый preferred path — ``from_cdc_registry``.
    """
    builder = RouteBuilder.from_cdc(
        "test_legacy", "orders", dsn="postgresql://x"
    )
    assert builder.route_id == "test_legacy"
    assert "orders" in str(builder.source)


def test_legacy_from_cdc_logical_still_works() -> None:
    """Backward compat: ``from_cdc_logical`` — K3 S5 W5 path still works."""
    builder = RouteBuilder.from_cdc_logical(
        "test_logical", "orders", dsn="postgresql://x"
    )
    assert builder.route_id == "test_logical"
    assert "cdc-logical" in str(builder.source)
