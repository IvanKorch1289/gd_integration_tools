"""Unit-тесты EventBusMixin (S18 W17, V22 NEW): .to_eventbus()/.from_eventbus().

Покрытие:
    * .to_eventbus(topic, payload_ref) добавляет EventBusPublishProcessor.
    * .from_eventbus(topic_pattern, ack_mode) добавляет EventBusSubscribeProcessor.
    * Chaining (.to_eventbus().to_eventbus()) работает.
    * to_spec() возвращает корректную dict-репрезентацию.
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.builders.eventbus_mixin import (
    EventBusPublishProcessor,
    EventBusSubscribeProcessor,
)


@pytest.fixture
def builder() -> RouteBuilder:
    return RouteBuilder.from_("test_route", source="internal:test")


class TestToEventBus:
    def test_adds_publish_processor(self, builder: RouteBuilder) -> None:
        b = builder.to_eventbus("orders.created", payload_ref="body")
        last = b._processors[-1]
        assert isinstance(last, EventBusPublishProcessor)
        assert last.topic == "orders.created"
        assert last.payload_ref == "body"

    def test_to_spec(self, builder: RouteBuilder) -> None:
        b = builder.to_eventbus("orders.created")
        spec = b._processors[-1].to_spec()
        assert spec == {
            "eventbus_publish": {
                "topic": "orders.created",
                "payload_ref": "body",
            }
        }

    def test_chainable(self, builder: RouteBuilder) -> None:
        b = (
            builder.to_eventbus("orders.created")
            .to_eventbus("audit.event", payload_ref="property:audit_payload")
        )
        assert len(b._processors) == 2


class TestFromEventBus:
    def test_adds_subscribe_processor(self, builder: RouteBuilder) -> None:
        b = builder.from_eventbus("orders.*", ack_mode="manual")
        last = b._processors[-1]
        assert isinstance(last, EventBusSubscribeProcessor)
        assert last.topic_pattern == "orders.*"
        assert last.ack_mode == "manual"

    def test_default_ack_mode_is_auto(self, builder: RouteBuilder) -> None:
        b = builder.from_eventbus("audit.>")
        assert b._processors[-1].ack_mode == "auto"

    def test_to_spec(self, builder: RouteBuilder) -> None:
        b = builder.from_eventbus("orders.>")
        spec = b._processors[-1].to_spec()
        assert spec == {
            "eventbus_subscribe": {
                "topic_pattern": "orders.>",
                "ack_mode": "auto",
            }
        }
