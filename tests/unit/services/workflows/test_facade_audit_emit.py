# ruff: noqa: S101
"""Тесты audit emit интеграции в :class:`WorkflowFacade` (Wave A.2)."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.security.capabilities import CapabilityGate, CapabilityRef
from src.backend.core.workflow import FakeWorkflowBackend
from src.backend.services.workflows import WorkflowFacade


class _CapturingSink:
    """Мини-стаб :class:`WorkflowAuditSink` для unit-тестов.

    Сохраняет каждый вызов ``emit(...)`` в публичный список ``calls``;
    при ``raise_on_emit=True`` пробрасывает RuntimeError — для проверки
    того, что facade поглощает ошибку.
    """

    def __init__(self, *, raise_on_emit: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.raise_on_emit = raise_on_emit

    async def emit(self, **kwargs: Any) -> None:
        if self.raise_on_emit:
            raise RuntimeError("ch unavailable")
        self.calls.append(kwargs)

    async def aclose(self) -> None:  # pragma: no cover — не используется в тестах
        return None


@pytest.fixture
def gate() -> CapabilityGate:
    g = CapabilityGate()
    g.declare(
        "ext.demo",
        [
            CapabilityRef(name="workflow.start", scope="wf.*"),
            CapabilityRef(name="workflow.signal", scope="wf.*"),
        ],
    )
    return g


@pytest.mark.asyncio
async def test_emit_on_start(gate: CapabilityGate) -> None:
    """После успешного start() facade вызывает sink.emit(workflow.start)."""
    sink = _CapturingSink()
    facade = WorkflowFacade(
        backend=FakeWorkflowBackend(), capability_gate=gate, audit_sink=sink
    )

    await facade.start(
        caller="ext.demo",
        workflow_name="demo",
        workflow_id="wf.1",
        input={},
        namespace="t",
        task_queue="q",
    )

    assert len(sink.calls) == 1
    call = sink.calls[0]
    assert call["event_type"] == "workflow.start"
    assert call["workflow_id"] == "wf.1"
    assert call["payload"]["caller"] == "ext.demo"


@pytest.mark.asyncio
async def test_emit_on_signal_and_cancel(gate: CapabilityGate) -> None:
    """signal() и cancel() тоже эмитят соответствующие события."""
    sink = _CapturingSink()
    facade = WorkflowFacade(
        backend=FakeWorkflowBackend(), capability_gate=gate, audit_sink=sink
    )
    handle = await facade.start(
        caller="ext.demo",
        workflow_name="demo",
        workflow_id="wf.2",
        input={},
        namespace="t",
        task_queue="q",
    )
    await facade.signal(
        caller="ext.demo", handle=handle, signal_name="approve", payload={}
    )
    await facade.cancel(caller="ext.demo", handle=handle)

    events = [c["event_type"] for c in sink.calls]
    assert events == ["workflow.start", "workflow.signal", "workflow.cancel"]


@pytest.mark.asyncio
async def test_emit_failure_does_not_break_workflow(gate: CapabilityGate) -> None:
    """Если sink.emit падает — facade.start всё равно возвращает handle."""
    sink = _CapturingSink(raise_on_emit=True)
    facade = WorkflowFacade(
        backend=FakeWorkflowBackend(), capability_gate=gate, audit_sink=sink
    )
    handle = await facade.start(
        caller="ext.demo",
        workflow_name="demo",
        workflow_id="wf.3",
        input={},
        namespace="t",
        task_queue="q",
    )
    assert handle.workflow_id == "wf.3"


@pytest.mark.asyncio
async def test_no_sink_noop(gate: CapabilityGate) -> None:
    """audit_sink=None — facade работает в no-op режиме без ошибок."""
    facade = WorkflowFacade(
        backend=FakeWorkflowBackend(), capability_gate=gate, audit_sink=None
    )
    handle = await facade.start(
        caller="ext.demo",
        workflow_name="demo",
        workflow_id="wf.4",
        input={},
        namespace="t",
        task_queue="q",
    )
    assert handle.workflow_id == "wf.4"
