"""S180 P1-#1: regression тесты для canonical ``DLQWriter`` path.

Проверяет, что ``ClickHouseAuditService`` использует canonical
:class:`DLQWriter` Protocol (через :meth:`set_dlq_writer` или
``__init__(dlq_writer=...)``) вместо legacy JSONL ``dlq_path``.

Acceptance:
- ``set_dlq_writer(InMemoryDLQWriter(...))`` — failed clicks пишутся как
  DLQEnvelope в InMemoryDLQWriter.records
- ``dlq_writer=`` через __init__ — то же самое
- ``dlq_writer`` имеет приоритет над ``dlq_path`` (если оба заданы —
  используется writer, file не создаётся)
- Envelope содержит: transport=clickhouse_audit, reason=UNEXPECTED,
  error_class=<ErrorClassName>, metadata.action
- Fire-and-forget: ошибка DLQ-writer НЕ пробрасывается caller'у
- Failed DLQ-writer логирует ERROR (без traceback spam)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, UTC
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.infrastructure.messaging.dlq.memory_writer import InMemoryDLQWriter
from src.backend.infrastructure.messaging.dlq_base import DLQReason
from src.backend.services.audit.clickhouse_audit_service import (
    AuditEvent,
    ClickHouseAuditService,
)


def _make_event(**kwargs: Any) -> AuditEvent:
    """Builds a minimal AuditEvent for tests."""
    defaults: dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC),
        "event_type": "test.dlq.event",
        "tenant_id": "tenant-42",
        "user_id": "user-7",
        "route_name": "/api/v1/test",
        "payload": {"key": "value"},
        "severity": "info",
    }
    defaults.update(kwargs)
    return AuditEvent(**defaults)


def _failing_client() -> AsyncMock:
    """AsyncMock ClickHouse client: ``insert()`` always raises RuntimeError."""
    client = AsyncMock()
    client.insert = AsyncMock(
        side_effect=RuntimeError("ClickHouse connection refused")
    )
    return client


def _flags_on() -> MagicMock:
    """feature_flags with audit_clickhouse_enabled=True."""
    mock_flags = MagicMock()
    mock_flags.audit_clickhouse_enabled = True
    return mock_flags


# ─── Test 1: set_dlq_writer через post-init setter ─────────────────────────


@pytest.mark.asyncio
async def test_set_dlq_writer_receives_envelope_on_failure() -> None:
    """set_dlq_writer() — failed emits пишутся в writer."""
    service = ClickHouseAuditService(client=_failing_client())
    writer = InMemoryDLQWriter()
    service.set_dlq_writer(writer)

    event = _make_event(event_id="set-writer-test", event_type="order.created")

    with patch("src.backend.core.config.features.feature_flags", _flags_on()):
        await service.emit(event)

    assert len(writer.records) == 1, (
        f"Expected 1 DLQ envelope, got {len(writer.records)}"
    )
    env = writer.records[0]
    assert env.transport == "clickhouse_audit"
    assert env.reason == DLQReason.UNEXPECTED
    assert env.error_class == "RuntimeError"
    assert "connection refused" in env.error_message
    assert env.tenant_id == "tenant-42"
    assert env.route_id == "/api/v1/test"
    assert env.original_payload is not None
    assert env.original_payload["event_id"] == "set-writer-test"
    assert env.metadata["action"] == "clickhouse_emit_failed"
    assert env.metadata["reason"] == "clickhouse_unavailable"
    assert env.dlq_class == "operational"


# ─── Test 2: dlq_writer через __init__ kwarg ────────────────────────────────


@pytest.mark.asyncio
async def test_init_dlq_writer_kwarg_receives_envelope() -> None:
    """Передача dlq_writer через __init__() — same behavior."""
    writer = InMemoryDLQWriter()
    service = ClickHouseAuditService(
        client=_failing_client(),
        dlq_writer=writer,
    )

    event = _make_event(event_id="init-kwarg-test")

    with patch("src.backend.core.config.features.feature_flags", _flags_on()):
        await service.emit(event)

    assert len(writer.records) == 1
    env = writer.records[0]
    assert env.error_class == "RuntimeError"


# ─── Test 3: приоритет dlq_writer > legacy dlq_path ─────────────────────────


@pytest.mark.asyncio
async def test_dlq_writer_priority_over_legacy_path(tmp_path: Any) -> None:
    """Если заданы и writer, и dlq_path — используется writer."""
    legacy_path = tmp_path / "legacy.jsonl"
    writer = InMemoryDLQWriter()
    service = ClickHouseAuditService(
        client=_failing_client(),
        dlq_path=legacy_path,
        dlq_writer=writer,
    )

    event = _make_event()

    with patch("src.backend.core.config.features.feature_flags", _flags_on()):
        await service.emit(event)

    # Writer получил envelope
    assert len(writer.records) == 1
    # Legacy path не создан (приоритет writer > legacy)
    assert not legacy_path.exists(), (
        "Legacy JSONL file should NOT be created when dlq_writer is set"
    )


# ─── Test 4: emit_batch через writer ────────────────────────────────────────


@pytest.mark.asyncio
async def test_emit_batch_through_writer() -> None:
    """emit_batch — каждое событие пишется в отдельный envelope."""
    writer = InMemoryDLQWriter()
    service = ClickHouseAuditService(
        client=_failing_client(),
        dlq_writer=writer,
    )

    events = [
        _make_event(event_id=f"batch-{i}", event_type="batch.event")
        for i in range(4)
    ]

    with patch("src.backend.core.config.features.feature_flags", _flags_on()):
        await service.emit_batch(events)

    assert len(writer.records) == 4, (
        f"Expected 4 envelopes (one per event), got {len(writer.records)}"
    )
    entity_ids = {env.original_payload["event_id"] for env in writer.records}
    assert entity_ids == {f"batch-{i}" for i in range(4)}


# ─── Test 5: успешный emit не пишет в DLQ ───────────────────────────────────


@pytest.mark.asyncio
async def test_successful_emit_does_not_write_dlq() -> None:
    """Успешный ClickHouse insert → no-op в DLQ-writer."""
    ok_client = AsyncMock()
    ok_client.insert = AsyncMock(return_value=None)
    writer = InMemoryDLQWriter()
    service = ClickHouseAuditService(
        client=ok_client,
        dlq_writer=writer,
    )

    event = _make_event()

    with patch("src.backend.core.config.features.feature_flags", _flags_on()):
        await service.emit(event)

    assert len(writer.records) == 0
    ok_client.insert.assert_called_once()


# ─── Test 6: feature flag OFF → no DLQ write ────────────────────────────────


@pytest.mark.asyncio
async def test_off_flag_does_not_write_dlq() -> None:
    """feature flag = OFF → ClickHouse skip + DLQ skip (no-op)."""
    writer = InMemoryDLQWriter()
    service = ClickHouseAuditService(
        client=_failing_client(),
        dlq_writer=writer,
    )

    event = _make_event()
    flags = MagicMock()
    flags.audit_clickhouse_enabled = False

    with patch("src.backend.core.config.features.feature_flags", flags):
        await service.emit(event)

    # Flag OFF → ClickHouse skip → DLQ never called.
    assert len(writer.records) == 0


# ─── Test 7: fire-and-forget (DLQ-writer raise) ────────────────────────────


@pytest.mark.asyncio
async def test_dlq_writer_failure_is_fire_and_forget() -> None:
    """DLQ-writer raise → caller НЕ получает исключение (audit-mid не валится)."""
    broken_writer = MagicMock()
    broken_writer.write = AsyncMock(
        side_effect=OSError("DLQ backend down")
    )
    service = ClickHouseAuditService(
        client=_failing_client(),
        dlq_writer=broken_writer,
    )
    event = _make_event()

    with patch("src.backend.core.config.features.feature_flags", _flags_on()):
        # Должен отработать без raise — caller (audit-middleware) не падает.
        await service.emit(event)

    broken_writer.write.assert_called_once()
