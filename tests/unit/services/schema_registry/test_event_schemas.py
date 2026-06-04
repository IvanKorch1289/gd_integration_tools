"""Unit tests for src.backend.services.schema_registry.event_schemas."""

from __future__ import annotations

from unittest.mock import patch

from src.backend.services.schema_registry.event_schemas import (
    register_default_event_schemas,
)
from src.backend.services.schema_registry.registry import (
    SchemaKind,
    ServiceSchemaRegistry,
)


class TestRegisterDefaultEventSchemas:
    def test_all_registered(self) -> None:
        reg = ServiceSchemaRegistry()
        with (
            patch(
                "src.backend.infrastructure.clients.messaging.event_bus.OrderEvent"
            ) as mock_order,
            patch(
                "src.backend.infrastructure.clients.messaging.event_bus.PipelineEvent"
            ) as mock_pipe,
            patch(
                "src.backend.infrastructure.clients.messaging.event_bus.FlagEvent"
            ) as mock_flag,
            patch(
                "src.backend.infrastructure.clients.messaging.event_bus.RouteEvent"
            ) as mock_route,
        ):
            mock_order.__name__ = "OrderEvent"
            mock_order.model_json_schema.return_value = {"type": "object"}
            mock_pipe.__name__ = "PipelineEvent"
            mock_pipe.model_json_schema.return_value = {"type": "object"}
            mock_flag.__name__ = "FlagEvent"
            mock_flag.model_json_schema.return_value = {"type": "object"}
            mock_route.__name__ = "RouteEvent"
            mock_route.model_json_schema.return_value = {"type": "object"}
            count = register_default_event_schemas(reg)
        assert count == 4
        assert reg.summary()["event"] == 4
        entry = reg.get(SchemaKind.EVENT, "events.events.orders.OrderEvent")
        assert entry is not None
        assert entry.meta["auto_registered"] is True

    def test_skip_on_exception(self) -> None:
        reg = ServiceSchemaRegistry()
        with (
            patch(
                "src.backend.infrastructure.clients.messaging.event_bus.OrderEvent"
            ) as mock_order,
            patch(
                "src.backend.infrastructure.clients.messaging.event_bus.PipelineEvent"
            ) as mock_pipe,
            patch(
                "src.backend.infrastructure.clients.messaging.event_bus.FlagEvent"
            ) as mock_flag,
            patch(
                "src.backend.infrastructure.clients.messaging.event_bus.RouteEvent"
            ) as mock_route,
        ):
            mock_order.__name__ = "OrderEvent"
            mock_order.model_json_schema.side_effect = RuntimeError("bad")
            mock_pipe.__name__ = "PipelineEvent"
            mock_pipe.model_json_schema.return_value = {"type": "object"}
            mock_flag.__name__ = "FlagEvent"
            mock_flag.model_json_schema.return_value = {"type": "object"}
            mock_route.__name__ = "RouteEvent"
            mock_route.model_json_schema.return_value = {"type": "object"}
            count = register_default_event_schemas(reg)
        assert count == 3
        assert reg.get(SchemaKind.EVENT, "events.events.orders.OrderEvent") is None
