"""W23 — контракт ``Source`` Protocol и ``SourceEvent``."""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.core.interfaces.sink import Sink, SinkKind, SinkResult
from src.core.interfaces.source import (
    EventCallback,
    Source,
    SourceEvent,
    SourceKind,
)


class _StubSource:
    source_id = "stub"
    kind = SourceKind.HTTP

    async def start(self, on_event: EventCallback) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def health(self) -> bool:
        return True


class _StubSink:
    sink_id = "stub-sink"
    kind = SinkKind.HTTP

    async def send(self, payload: object) -> SinkResult:
        return SinkResult(ok=True)

    async def health(self) -> bool:
        return True


def test_source_protocol_compliance() -> None:
    assert isinstance(_StubSource(), Source)


def test_sink_protocol_compliance() -> None:
    assert isinstance(_StubSink(), Sink)


def test_source_event_defaults() -> None:
    event = SourceEvent(source_id="x", kind=SourceKind.WEBHOOK, payload={"k": 1})
    assert event.source_id == "x"
    assert event.kind is SourceKind.WEBHOOK
    assert event.event_id  # uuid4 default
    assert event.event_time.tzinfo is not None  # UTC


@pytest.mark.parametrize("kind", list(SourceKind))
def test_all_source_kinds_have_value(kind: SourceKind) -> None:
    assert isinstance(kind.value, str)
    assert kind.value
