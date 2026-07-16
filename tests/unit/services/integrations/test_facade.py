"""Unit-тесты для IntegrationFacade (S203 W4)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.interfaces.sink import SinkKind, SinkResult
from src.backend.services.integrations.facade import IntegrationFacade


class _FakeSink:
    """Sink stub для тестов без registry dependencies."""

    def __init__(self, sink_id: str, kind: SinkKind = SinkKind.HTTP) -> None:
        self.sink_id = sink_id
        self.kind = kind

    async def send(self, payload):
        return SinkResult(ok=True, external_id="ext-1", details={"to": "ok"})

    async def health(self, mode: str = "fast"):
        from src.backend.infrastructure.clients.base_connector import HealthResult

        return HealthResult.ok(latency_ms=1.0, mode=mode, kind=self.kind.value)


class TestIntegrationFacadeSendToSink:
    """S203 W4: capability-gated отправка в Sink."""

    async def test_send_allowed(self, monkeypatch) -> None:
        """Если capability granted → sink.send() вызывается."""
        sink = _FakeSink("alerts.http", SinkKind.HTTP)
        facade = IntegrationFacade()
        facade._sinks = MagicMock()
        facade._sinks.get.return_value = sink

        # Подменяем _check_capability → True
        facade._check_capability = AsyncMock(return_value=True)

        result = await facade.send_to_sink("alerts.http", {"msg": "hi"})
        assert result.ok is True
        assert result.external_id == "ext-1"

    async def test_send_denied_raises_capability_error(self, monkeypatch) -> None:
        """Если capability denied → CapabilityDeniedError."""
        from src.backend.core.security.capabilities.errors import (
            CapabilityDeniedError,
        )

        sink = _FakeSink("alerts.http", SinkKind.HTTP)
        facade = IntegrationFacade()
        facade._sinks = MagicMock()
        facade._sinks.get.return_value = sink
        facade._check_capability = AsyncMock(return_value=False)

        with pytest.raises(CapabilityDeniedError):
            await facade.send_to_sink("alerts.http", {"msg": "hi"})

    async def test_capability_name_format(self, monkeypatch) -> None:
        """Capability формат: sink.send.<kind>."""
        sink = _FakeSink("alerts.mq", SinkKind.MQ)
        facade = IntegrationFacade()
        facade._sinks = MagicMock()
        facade._sinks.get.return_value = sink

        captured: dict = {}
        async def _capture_cap(cap, *, context=None):
            captured["cap"] = cap
            return True

        facade._check_capability = _capture_cap

        await facade.send_to_sink("alerts.mq", {"msg": "hi"})
        assert captured["cap"] == "sink.send.mq"


class TestIntegrationFacadeHealth:
    """S203 W4: read-only health checks (no capability)."""

    async def test_check_sink_health(self) -> None:
        sink = _FakeSink("alerts.http", SinkKind.HTTP)
        facade = IntegrationFacade()
        facade._sinks = MagicMock()
        facade._sinks.get.return_value = sink

        result = await facade.check_sink_health("alerts.http")
        assert result["status"] == "ok"
        assert result["latency_ms"] >= 0

    async def test_check_source_health_not_found(self) -> None:
        """KeyError если source не зарегистрирован."""
        facade = IntegrationFacade()
        facade._sources = MagicMock()
        facade._sources.get.side_effect = KeyError("unknown")

        with pytest.raises(KeyError):
            await facade.check_source_health("unknown_source")


class TestIntegrationFacadeIntrospection:
    """S203 W4: list_sinks/list_sources для DSL discoverability."""

    def test_list_sinks(self) -> None:
        s1 = _FakeSink("a.http", SinkKind.HTTP)
        s2 = _FakeSink("b.mq", SinkKind.MQ)
        facade = IntegrationFacade()
        facade._sinks = MagicMock()
        facade._sinks.all.return_value = (s1, s2)

        ids = facade.list_sinks()
        assert ids == ("a.http", "b.mq")