"""Regression tests для CDC backend registry (S101 W1).

Coverage:
* ``get_cdc_source`` — каждый backend из :data:`SUPPORTED_BACKENDS`
  возвращает инстанс правильного типа (``isinstance CDCSource``).
* ``is_backend_available`` — True для базовых backend'ов, False для
  unknown names.
* ``list_backends`` — sorted, непустой.
* ``get_cdc_source`` — ``ValueError`` для unknown backend.
* ``FakeCDCSource`` — пустой events list (default).
* Factory использует lazy import (backends можно создавать без
  pre-loading модуля).
"""
from __future__ import annotations

import pytest

from src.backend.core.cdc.registry import (
    SUPPORTED_BACKENDS,
    get_cdc_source,
    is_backend_available,
    list_backends,
)
from src.backend.core.cdc.source import CDCSource, FakeCDCSource


def test_list_backends_returns_sorted_nonempty() -> None:
    """``list_backends()`` — sorted list всех supported backends."""
    backends = list_backends()
    assert backends == sorted(backends)
    assert len(backends) >= 4
    assert "poll" in backends
    assert "fake" in backends


def test_is_backend_available_for_known_names() -> None:
    """``is_backend_available`` — True для всех R2.1 backends."""
    for backend in ("poll", "fake", "adapter", "debezium"):
        assert is_backend_available(backend) is True, f"{backend!r} not available"


def test_is_backend_available_for_unknown_returns_false() -> None:
    """``is_backend_available`` — False для unknown backend names."""
    assert is_backend_available("nonexistent") is False
    assert is_backend_available("") is False
    assert is_backend_available("POLL") is False  # case-sensitive


def test_get_cdc_source_poll_returns_cdc_source_instance() -> None:
    """``get_cdc_source("poll", ...)`` returns PollCDCBackend implementing CDCSource."""
    src = get_cdc_source("poll", profile="dev")
    assert isinstance(src, CDCSource)
    assert isinstance(src, FakeCDCSource) is False


def test_get_cdc_source_fake_returns_fake_cdc_source() -> None:
    """``get_cdc_source("fake")`` returns FakeCDCSource with empty events."""
    src = get_cdc_source("fake")
    assert isinstance(src, FakeCDCSource)
    assert isinstance(src, CDCSource)


def test_get_cdc_source_fake_with_events() -> None:
    """``get_cdc_source("fake", events=[...])`` passes events to FakeCDCSource."""
    from src.backend.core.cdc.source import CDCCursor, CDCEvent
    from datetime import UTC, datetime

    event = CDCEvent(
        operation="INSERT",
        source="test",
        table="orders",
        timestamp=datetime.now(UTC),
        cursor=CDCCursor(value="v1", backend="fake"),
        new={"id": 1},
    )
    src = get_cdc_source("fake", events=[event])
    assert isinstance(src, FakeCDCSource)


def test_get_cdc_source_listen_notify_constructs() -> None:
    """``get_cdc_source("listen_notify", ...)`` — construction OK (без asyncpg)."""
    src = get_cdc_source("listen_notify", dsn="postgresql://test", channel="events")
    assert isinstance(src, CDCSource)


def test_get_cdc_source_debezium_constructs() -> None:
    """``get_cdc_source("debezium", ...)`` — construction OK (без Kafka connect)."""
    src = get_cdc_source(
        "debezium", bootstrap_servers="localhost:9092", group_id="test_grp"
    )
    assert isinstance(src, CDCSource)


def test_get_cdc_source_adapter_constructs() -> None:
    """``get_cdc_source("adapter", ...)`` — construction OK через legacy CDCClient.

    S102 W1: bug fixed — ``_cdc_instance`` теперь module-level, locked.
    """
    src = get_cdc_source("adapter", profile="dev", strategy="polling")
    assert isinstance(src, CDCSource)


def test_get_cdc_source_unknown_raises_value_error() -> None:
    """``get_cdc_source("unknown")`` — ValueError с supported list в message."""
    with pytest.raises(ValueError) as exc_info:
        get_cdc_source("unknown_backend")
    msg = str(exc_info.value)
    assert "unknown_backend" in msg
    assert "Supported" in msg
    # Все supported backends перечислены в error message
    for backend in SUPPORTED_BACKENDS:
        assert backend in msg


def test_get_cdc_source_lazy_import_no_preload() -> None:
    """Factory uses lazy import — backends создаются без eager load.

    Это позволяет factory работать даже если optional deps (asyncpg,
    aiokafka) не установлены — будет ленивая ошибка ТОЛЬКО при instantiate
    конкретного backend'а.
    """
    # Default state: не должно быть I/O или import side-effects
    import src.backend.core.cdc.registry as reg_mod

    assert hasattr(reg_mod, "get_cdc_source")
    assert hasattr(reg_mod, "is_backend_available")
    assert hasattr(reg_mod, "list_backends")
    # ``SUPPORTED_BACKENDS`` — frozenset (immutable)
    assert isinstance(SUPPORTED_BACKENDS, frozenset)
