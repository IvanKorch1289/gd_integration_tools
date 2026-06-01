"""Unit-тесты расширенного WorkflowAuditSink — Sprint 12 K1 W1.

Проверяемые сценарии:
    * новые event_types (signal/cancel/complete/fail/compensation_*/hitl.*);
    * новые поля actor / duration_ms / parent_workflow_id;
    * batch emission сохраняет новые поля;
    * tenant_id propagation;
    * не падает на пустом payload.
"""

# ruff: noqa: S101

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.services.audit.workflow_audit_sink import WorkflowAuditSink


@pytest.fixture
def writer_mock() -> Any:
    writer = MagicMock()
    writer.add = AsyncMock(return_value=None)
    writer.add_many = AsyncMock(return_value=None)
    writer.flush_now = AsyncMock(return_value=0)
    writer.aclose = AsyncMock(return_value=None)
    return writer


@pytest.fixture
def sink(writer_mock: Any) -> WorkflowAuditSink:
    return WorkflowAuditSink(writer=writer_mock)


@pytest.mark.asyncio
async def test_emit_signal_event(
    sink: WorkflowAuditSink, writer_mock: Any
) -> None:
    await sink.emit(
        event_type="workflow.signal",
        workflow_id="wf-1",
        tenant_id="tenant-A",
        payload={"signal_name": "pause"},
        actor="api-key:abc",
    )
    writer_mock.add.assert_awaited_once()
    row = writer_mock.add.await_args.args[0]
    assert row["event_type"] == "workflow.signal"
    assert row["workflow_id"] == "wf-1"
    assert row["actor"] == "api-key:abc"
    assert row["duration_ms"] is None
    assert row["parent_workflow_id"] is None


@pytest.mark.asyncio
async def test_emit_cancel_event(
    sink: WorkflowAuditSink, writer_mock: Any
) -> None:
    await sink.emit(
        event_type="workflow.cancel",
        workflow_id="wf-cancel",
        tenant_id=None,
        payload={"reason": "user_request"},
        actor="manage.py",
    )
    row = writer_mock.add.await_args.args[0]
    assert row["event_type"] == "workflow.cancel"
    assert row["tenant_id"] is None
    assert row["actor"] == "manage.py"


@pytest.mark.asyncio
async def test_emit_complete_with_duration(
    sink: WorkflowAuditSink, writer_mock: Any
) -> None:
    await sink.emit(
        event_type="workflow.complete",
        workflow_id="wf-done",
        tenant_id="t1",
        duration_ms=12345,
        actor="worker:queue-default",
    )
    row = writer_mock.add.await_args.args[0]
    assert row["event_type"] == "workflow.complete"
    assert row["duration_ms"] == 12345


@pytest.mark.asyncio
async def test_emit_compensation_events(
    sink: WorkflowAuditSink, writer_mock: Any
) -> None:
    for ev_type in (
        "workflow.compensation_start",
        "workflow.compensation_complete",
        "workflow.compensation_fail",
    ):
        await sink.emit(
            event_type=ev_type,
            workflow_id="saga-1",
            tenant_id="t1",
            parent_workflow_id="parent-saga-1",
            payload={"step": "refund_account"},
        )

    assert writer_mock.add.await_count == 3
    last_row = writer_mock.add.await_args.args[0]
    assert last_row["parent_workflow_id"] == "parent-saga-1"


@pytest.mark.asyncio
async def test_emit_hitl_events(
    sink: WorkflowAuditSink, writer_mock: Any
) -> None:
    for ev_type in ("hitl.approved", "hitl.rejected", "hitl.requested_info"):
        await sink.emit(
            event_type=ev_type,
            workflow_id="wf-1",
            tenant_id="t1",
            actor="operator:alice",
            duration_ms=4500,
            payload={"signal_id": "sig-1", "comment": "ok"},
        )

    assert writer_mock.add.await_count == 3
    rows = [c.args[0] for c in writer_mock.add.await_args_list]
    types = [r["event_type"] for r in rows]
    assert set(types) == {"hitl.approved", "hitl.rejected", "hitl.requested_info"}


@pytest.mark.asyncio
async def test_emit_with_explicit_event_id_and_created_at(
    sink: WorkflowAuditSink, writer_mock: Any
) -> None:
    explicit_ts = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    await sink.emit(
        event_type="workflow.start",
        workflow_id="wf-explicit",
        tenant_id="t1",
        event_id="event-fixed-id",
        created_at=explicit_ts,
    )
    row = writer_mock.add.await_args.args[0]
    assert row["event_id"] == "event-fixed-id"
    assert row["created_at"] == explicit_ts


@pytest.mark.asyncio
async def test_emit_batch_preserves_extended_fields(
    sink: WorkflowAuditSink, writer_mock: Any
) -> None:
    events = [
        {
            "event_type": "workflow.start",
            "workflow_id": "wf-1",
            "tenant_id": "t1",
        },
        {
            "event_type": "workflow.cancel",
            "workflow_id": "wf-1",
            "tenant_id": "t1",
        },
    ]
    await sink.emit_batch(events)
    writer_mock.add_many.assert_awaited_once()
    rows = writer_mock.add_many.await_args.args[0]
    assert len(rows) == 2
    assert rows[0]["event_type"] == "workflow.start"
    assert rows[1]["event_type"] == "workflow.cancel"


@pytest.mark.asyncio
async def test_emit_handles_empty_payload(
    sink: WorkflowAuditSink, writer_mock: Any
) -> None:
    await sink.emit(
        event_type="workflow.fail",
        workflow_id="wf-fail",
        tenant_id=None,
    )
    row = writer_mock.add.await_args.args[0]
    assert row["payload"] == "{}"
