"""Unit tests for src.backend.schemas.health_events."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.backend.schemas.health_events import HealthTransitionEvent


@pytest.mark.unit
class TestHealthTransitionEvent:
    def test_create_minimal(self) -> None:
        event = HealthTransitionEvent(previous_status="degraded", current_status="healthy")
        assert event.previous_status == "degraded"
        assert event.current_status == "healthy"
        assert event.components == {}

    def test_create_with_components(self) -> None:
        components = {
            "db": {"status": "healthy", "latency_ms": 12},
            "queue": {"status": "degraded", "message": "backpressure"},
        }
        event = HealthTransitionEvent(
            previous_status="healthy",
            current_status="degraded",
            components=components,
        )
        assert event.components == components

    def test_components_default_factory_isolated(self) -> None:
        """Each instance should get its own dict, not a shared reference."""
        event_a = HealthTransitionEvent(previous_status="a", current_status="b")
        event_b = HealthTransitionEvent(previous_status="c", current_status="d")
        event_a.components["x"] = 1
        assert "x" not in event_b.components

    def test_missing_previous_status_raises(self) -> None:
        with pytest.raises(ValidationError):
            HealthTransitionEvent(current_status="healthy")  # type: ignore[call-arg]

    def test_missing_current_status_raises(self) -> None:
        with pytest.raises(ValidationError):
            HealthTransitionEvent(previous_status="healthy")  # type: ignore[call-arg]

    def test_serialize_roundtrip(self) -> None:
        event = HealthTransitionEvent(
            previous_status="unknown",
            current_status="healthy",
            components={"cache": {"status": "ok"}},
        )
        payload = event.model_dump()
        restored = HealthTransitionEvent.model_validate(payload)
        assert restored == event

    def test_fields_have_descriptions(self) -> None:
        fields = HealthTransitionEvent.model_fields
        assert fields["previous_status"].description == "Предыдущий overall-статус"
        assert fields["current_status"].description == "Текущий overall-статус"
        assert fields["components"].description == "Снимок компонентных проверок"

    def test_all_exported(self) -> None:
        from src.backend.schemas import health_events

        assert health_events.__all__ == ("HealthTransitionEvent",)
