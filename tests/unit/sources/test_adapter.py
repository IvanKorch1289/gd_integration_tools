"""W23 — SourceToInvokerAdapter."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.interfaces.invoker import (
    InvocationMode,
    InvocationRequest,
    InvocationResponse,
    InvocationStatus,
)
from src.backend.core.interfaces.source import SourceEvent, SourceKind
from src.backend.services.sources.adapter import SourceToInvokerAdapter
from src.backend.services.sources.idempotency import MemoryDedupeStore


class _StubInvoker:
    def __init__(self) -> None:
        self.calls: list[InvocationRequest] = []

    async def invoke(self, request: InvocationRequest) -> InvocationResponse:
        self.calls.append(request)
        return InvocationResponse(
            invocation_id=request.invocation_id,
            status=InvocationStatus.OK,
            result={"echo": request.payload},
            mode=request.mode,
        )


def _event(event_id: str = "e1") -> SourceEvent:
    return SourceEvent(
        source_id="src1",
        kind=SourceKind.WEBHOOK,
        payload={"k": "v"},
        event_id=event_id,
    )


@pytest.mark.asyncio
async def test_adapter_calls_invoker() -> None:
    inv = _StubInvoker()
    adapter = SourceToInvokerAdapter(inv, action="orders.process")
    resp = await adapter.handle(_event())
    assert resp is not None
    assert resp.status is InvocationStatus.OK
    assert len(inv.calls) == 1
    req = inv.calls[0]
    assert req.action == "orders.process"
    assert req.mode is InvocationMode.SYNC
    assert req.payload["data"] == {"k": "v"}
    assert req.payload["source_id"] == "src1"


@pytest.mark.asyncio
async def test_adapter_skips_duplicates() -> None:
    inv = _StubInvoker()
    dedupe = MemoryDedupeStore()
    adapter = SourceToInvokerAdapter(inv, action="x.y", dedupe=dedupe)
    first = await adapter.handle(_event("e-dup"))
    second = await adapter.handle(_event("e-dup"))
    assert first is not None
    assert second is None
    assert len(inv.calls) == 1


@pytest.mark.asyncio
async def test_payload_mapper_overrides_default() -> None:
    inv = _StubInvoker()

    def mapper(ev: SourceEvent) -> dict[str, object]:
        return {"only": ev.payload}

    adapter = SourceToInvokerAdapter(inv, action="x.y", payload_mapper=mapper)
    await adapter.handle(_event())
    assert inv.calls[0].payload == {"only": {"k": "v"}}


@pytest.mark.asyncio
async def test_adapter_propagates_invoker_error() -> None:
    class _Boom:
        async def invoke(self, request: InvocationRequest) -> Any:
            raise RuntimeError("boom")

    adapter = SourceToInvokerAdapter(_Boom(), action="x.y")
    with pytest.raises(RuntimeError):
        await adapter.handle(_event())
