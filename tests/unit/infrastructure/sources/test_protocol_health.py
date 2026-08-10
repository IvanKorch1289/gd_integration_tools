"""Tests for updated Source/Sink health protocol signature."""
from __future__ import annotations

import pytest

from src.backend.core.interfaces.sink import Sink, SinkKind
from src.backend.core.interfaces.source import Source, SourceKind
from src.backend.infrastructure.clients.base_connector import HealthResult


@pytest.mark.unit
async def test_source_protocol_has_health_result_signature() -> None:
    """Source.health must accept mode kwarg and return HealthResult."""

    class StubSource:
        source_id = "test"
        kind = SourceKind.HTTP

        async def start(self, on_event) -> None: ...

        async def stop(self) -> None: ...

        async def health(self, mode: str = "fast") -> HealthResult:
            return HealthResult.ok(latency_ms=0.1, mode=mode)

    obj = StubSource()
    assert isinstance(obj, Source)
    result = await obj.health(mode="deep")
    assert isinstance(result, HealthResult)
    assert result.mode == "deep"


@pytest.mark.unit
async def test_sink_protocol_has_health_result_signature() -> None:
    """Sink.health must accept mode kwarg and return HealthResult."""

    class StubSink:
        sink_id = "test"
        kind = SinkKind.HTTP

        async def send(self, payload) -> object: ...

        async def health(self, mode: str = "fast") -> HealthResult:
            return HealthResult.ok(latency_ms=0.1, mode=mode)

    obj = StubSink()
    assert isinstance(obj, Sink)
    result = await obj.health(mode="deep")
    assert isinstance(result, HealthResult)
