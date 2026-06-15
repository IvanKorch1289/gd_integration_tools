"""Unit-тесты EventBusPublishProcessor runtime (S133 W4).

Покрытие:
    * feature-flag OFF → no-op.
    * EventBus не запущен → fallback в ``exchange.properties``.
    * EventBus запущен → публикация через ``bus.publish()``.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.builders.eventbus_mixin import EventBusPublishProcessor
from src.backend.dsl.engine.exchange import Exchange, Message


def _exchange(body: Any = None, properties: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(
        in_message=Message(body=body, headers={}),
        properties=properties or {},
    )


@pytest.mark.asyncio
async def test_noop_when_feature_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """При eventbus_dsl_enabled=False процессор ничего не делает."""
    monkeypatch.setattr(
        "src.backend.core.config.features.feature_flags.eventbus_dsl_enabled",
        False,
        raising=False,
    )
    proc = EventBusPublishProcessor(topic="orders.created")
    ex = _exchange(body={"id": 1})

    await proc.process(ex, context=MagicMock())

    assert "_eventbus_published" not in ex.properties


@pytest.mark.asyncio
async def test_fallback_when_bus_not_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если EventBus не стартовал — событие падает в properties."""
    monkeypatch.setattr(
        "src.backend.core.config.features.feature_flags.eventbus_dsl_enabled",
        True,
        raising=False,
    )
    fake_bus = MagicMock()
    fake_bus._broker = None
    fake_bus._started = False
    monkeypatch.setattr(
        "src.backend.core.messaging.event_bus.get_event_bus", lambda: fake_bus
    )

    proc = EventBusPublishProcessor(topic="orders.created")
    ex = _exchange(body={"id": 1})

    await proc.process(ex, context=MagicMock())

    assert ex.properties["_eventbus_published"] == [
        {"topic": "orders.created", "payload": {"id": 1}}
    ]


@pytest.mark.asyncio
async def test_publish_when_bus_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EventBus запущен → публикация в брокер, без fallback."""
    monkeypatch.setattr(
        "src.backend.core.config.features.feature_flags.eventbus_dsl_enabled",
        True,
        raising=False,
    )
    fake_bus = MagicMock()
    fake_bus._broker = MagicMock()
    fake_bus._started = True
    fake_bus.publish = AsyncMock()
    monkeypatch.setattr(
        "src.backend.core.messaging.event_bus.get_event_bus", lambda: fake_bus
    )

    proc = EventBusPublishProcessor(topic="orders.created")
    ex = _exchange(body={"id": 1}, properties={"correlation_id": "cid-123"})

    await proc.process(ex, context=MagicMock())

    fake_bus.publish.assert_awaited_once()
    call_args = fake_bus.publish.await_args
    assert call_args is not None
    channel, event = call_args.args
    assert channel == "orders.created"
    assert event.topic == "orders.created"
    assert event.payload == {"id": 1}
    assert event.correlation_id == "cid-123"
    assert "_eventbus_published" not in ex.properties


@pytest.mark.asyncio
async def test_property_payload_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    """payload_ref='property:<name>' забирает значение из properties."""
    monkeypatch.setattr(
        "src.backend.core.config.features.feature_flags.eventbus_dsl_enabled",
        True,
        raising=False,
    )
    fake_bus = MagicMock()
    fake_bus._broker = MagicMock()
    fake_bus._started = True
    fake_bus.publish = AsyncMock()
    monkeypatch.setattr(
        "src.backend.core.messaging.event_bus.get_event_bus", lambda: fake_bus
    )

    proc = EventBusPublishProcessor(
        topic="audit.event", payload_ref="property:audit_payload"
    )
    ex = _exchange(properties={"audit_payload": {"user": "alice"}})

    await proc.process(ex, context=MagicMock())

    event = fake_bus.publish.await_args.args[1]
    assert event.payload == {"user": "alice"}


@pytest.mark.asyncio
async def test_publish_failure_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При исключении publish — fallback в properties."""
    monkeypatch.setattr(
        "src.backend.core.config.features.feature_flags.eventbus_dsl_enabled",
        True,
        raising=False,
    )
    fake_bus = MagicMock()
    fake_bus._broker = MagicMock()
    fake_bus._started = True
    fake_bus.publish = AsyncMock(side_effect=RuntimeError("broker down"))
    monkeypatch.setattr(
        "src.backend.core.messaging.event_bus.get_event_bus", lambda: fake_bus
    )

    proc = EventBusPublishProcessor(topic="orders.created")
    ex = _exchange(body={"id": 1})

    await proc.process(ex, context=MagicMock())

    assert ex.properties["_eventbus_published"] == [
        {"topic": "orders.created", "payload": {"id": 1}}
    ]
