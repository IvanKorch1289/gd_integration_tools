"""W23 — start_all_sources / stop_all_sources + e2e через адаптер."""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.core.config.source_spec import SourceSpec
from src.backend.core.interfaces.invoker import (
    InvocationRequest,
    InvocationResponse,
    InvocationStatus,
)
from src.backend.core.interfaces.source import EventCallback, SourceEvent, SourceKind
from src.backend.services.sources.idempotency import MemoryDedupeStore
from src.backend.services.sources.lifecycle import start_all_sources, stop_all_sources
from src.backend.services.sources.registry import SourceRegistry


class _StubSource:
    def __init__(self, sid: str) -> None:
        self.source_id = sid
        self.kind = SourceKind.WEBHOOK
        self.received_cb: EventCallback | None = None
        self.stopped = False

    async def start(self, on_event: EventCallback) -> None:
        self.received_cb = on_event

    async def stop(self) -> None:
        self.stopped = True

    async def health(self) -> bool:
        return True


class _StubInvoker:
    def __init__(self) -> None:
        self.calls: list[InvocationRequest] = []

    async def invoke(self, request: InvocationRequest) -> InvocationResponse:
        self.calls.append(request)
        return InvocationResponse(
            invocation_id=request.invocation_id,
            status=InvocationStatus.OK,
        )


@pytest.mark.asyncio
async def test_start_then_stop_all() -> None:
    registry = SourceRegistry()
    src1 = _StubSource("s1")
    src2 = _StubSource("s2")
    registry.register(src1)
    registry.register(src2)
    invoker = _StubInvoker()

    specs = [
        SourceSpec(id="s1", kind="webhook", action="a1"),
        SourceSpec(id="s2", kind="webhook", action="a2"),
    ]
    await start_all_sources(registry=registry, invoker=invoker, specs=specs)
    assert src1.received_cb is not None
    assert src2.received_cb is not None

    # Триггерим событие через адаптер первого source.
    assert src1.received_cb is not None
    await src1.received_cb(
        SourceEvent(source_id="s1", kind=SourceKind.WEBHOOK, payload={"x": 1})
    )
    assert len(invoker.calls) == 1
    assert invoker.calls[0].action == "a1"

    await stop_all_sources(registry)
    assert src1.stopped is True
    assert src2.stopped is True


@pytest.mark.asyncio
async def test_idempotency_skipped_when_disabled() -> None:
    registry = SourceRegistry()
    src = _StubSource("s")
    registry.register(src)
    invoker = _StubInvoker()
    spec = SourceSpec(id="s", kind="webhook", action="a", idempotency=False)

    await start_all_sources(
        registry=registry,
        invoker=invoker,
        specs=[spec],
        dedupe=MemoryDedupeStore(),
    )
    assert src.received_cb is not None
    ev = SourceEvent(
        source_id="s", kind=SourceKind.WEBHOOK, payload={"x": 1}, event_id="dup"
    )
    await src.received_cb(ev)
    await src.received_cb(ev)  # обычно был бы дубль, но idempotency=False
    assert len(invoker.calls) == 2
    await stop_all_sources(registry)


@pytest.mark.asyncio
async def test_missing_source_warns_not_raises() -> None:
    """Spec для незарегистрированного source должен пропускаться без падения."""
    registry = SourceRegistry()
    invoker = _StubInvoker()
    spec = SourceSpec(id="missing", kind="webhook", action="x")
    # Не должно бросить
    await start_all_sources(registry=registry, invoker=invoker, specs=[spec])
    assert invoker.calls == []
