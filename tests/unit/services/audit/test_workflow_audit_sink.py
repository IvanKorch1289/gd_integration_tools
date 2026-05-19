"""Unit-тесты WorkflowAuditSink (S12 K1 W1).

Покрывает:
    1. emit_basic — single event попадает во writer с правильной схемой.
    2. emit_batch — пакет событий через add_many.
    3. trace_id_propagation — trace_id сохраняется как-есть.
    4. tenant_filtering — поле tenant_id корректно проходит как None.
    5. flush — flush_now делегируется во writer.
    6. graceful_close — aclose дёргает writer.aclose.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from src.backend.services.audit.workflow_audit_sink import WorkflowAuditSink


class _StubBulkWriter:
    """Минимальный stub :class:`ClickHouseBulkWriter` для unit-тестов.

    Хранит все добавленные строки в ``rows`` и считает вызовы методов.
    """

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.flush_called: int = 0
        self.close_called: int = 0

    async def add(self, row: dict[str, Any]) -> None:
        self.rows.append(row)

    async def add_many(self, rows: list[dict[str, Any]]) -> None:
        self.rows.extend(rows)

    async def flush_now(self) -> int:
        self.flush_called += 1
        flushed = len(self.rows)
        return flushed

    async def aclose(self) -> None:
        self.close_called += 1


@pytest.mark.asyncio
async def test_emit_basic_schema() -> None:
    """emit() формирует row со всеми обязательными полями."""
    writer = _StubBulkWriter()
    sink = WorkflowAuditSink(writer=writer)

    await sink.emit(
        event_type="workflow.start",
        workflow_id="wf-001",
        tenant_id="tenant-A",
        payload={"input": {"k": 1}},
        trace_id="trace-xyz",
    )
    assert len(writer.rows) == 1
    row = writer.rows[0]
    assert row["event_type"] == "workflow.start"
    assert row["workflow_id"] == "wf-001"
    assert row["tenant_id"] == "tenant-A"
    assert row["trace_id"] == "trace-xyz"
    # event_id — UUID-строка.
    assert isinstance(row["event_id"], str) and len(row["event_id"]) >= 32
    # payload — JSON-строка.
    assert json.loads(row["payload"]) == {"input": {"k": 1}}
    # created_at — timezone-aware UTC.
    assert isinstance(row["created_at"], datetime)
    assert row["created_at"].tzinfo is timezone.utc


@pytest.mark.asyncio
async def test_emit_batch_delegates_to_add_many() -> None:
    """emit_batch() агрегирует rows и кидает их через add_many."""
    writer = _StubBulkWriter()
    sink = WorkflowAuditSink(writer=writer)

    await sink.emit_batch(
        [
            {"event_type": "activity.start", "workflow_id": "wf-1"},
            {
                "event_type": "activity.complete",
                "workflow_id": "wf-1",
                "tenant_id": "tenant-B",
            },
        ]
    )
    assert len(writer.rows) == 2
    assert writer.rows[0]["event_type"] == "activity.start"
    assert writer.rows[0]["tenant_id"] is None
    assert writer.rows[1]["tenant_id"] == "tenant-B"
    # Пустой пакет — no-op.
    await sink.emit_batch([])
    assert len(writer.rows) == 2


@pytest.mark.asyncio
async def test_emit_trace_id_optional() -> None:
    """trace_id может быть None — поле сохраняется как None."""
    writer = _StubBulkWriter()
    sink = WorkflowAuditSink(writer=writer)

    await sink.emit(
        event_type="workflow.signal",
        workflow_id="wf-2",
        tenant_id=None,
        payload=None,
        trace_id=None,
    )
    row = writer.rows[0]
    assert row["trace_id"] is None
    assert row["tenant_id"] is None
    # payload=None → пустой JSON-объект.
    assert json.loads(row["payload"]) == {}


@pytest.mark.asyncio
async def test_emit_explicit_event_id_and_timestamp() -> None:
    """event_id и created_at можно задать явно — они не перезаписываются."""
    writer = _StubBulkWriter()
    sink = WorkflowAuditSink(writer=writer)

    custom_id = "00000000-0000-0000-0000-000000000001"
    custom_ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    await sink.emit(
        event_type="workflow.complete",
        workflow_id="wf-3",
        tenant_id="tenant-C",
        event_id=custom_id,
        created_at=custom_ts,
    )
    row = writer.rows[0]
    assert row["event_id"] == custom_id
    assert row["created_at"] == custom_ts


@pytest.mark.asyncio
async def test_flush_delegates_to_writer() -> None:
    """flush() прокидывает вызов в writer.flush_now()."""
    writer = _StubBulkWriter()
    sink = WorkflowAuditSink(writer=writer)
    await sink.emit(
        event_type="workflow.fail",
        workflow_id="wf-4",
        tenant_id=None,
    )
    flushed = await sink.flush()
    assert writer.flush_called == 1
    assert flushed == 1


@pytest.mark.asyncio
async def test_aclose_delegates_to_writer() -> None:
    """aclose() прокидывает graceful shutdown в writer."""
    writer = _StubBulkWriter()
    sink = WorkflowAuditSink(writer=writer)
    await sink.aclose()
    assert writer.close_called == 1


def test_table_name_constant() -> None:
    """table_name — стабильная константа ``workflow_audit``."""
    sink = WorkflowAuditSink(writer=_StubBulkWriter())
    assert sink.table_name == "workflow_audit"
