"""Unit-tests for AuditEventLog."""

# ruff: noqa: S101

from __future__ import annotations

import sys
import types
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.infrastructure.audit.event_log import (
    AuditEvent,
    AuditEventLog,
    emit_audit_event,
    get_audit_log,
)


@pytest.fixture
def fresh_audit_log(monkeypatch: pytest.MonkeyPatch) -> AuditEventLog:
    """Return a fresh AuditEventLog instance and reset global singleton."""
    monkeypatch.setattr(
        "src.backend.infrastructure.audit.event_log._audit_log", None, raising=False
    )
    log = AuditEventLog(table="audit_events", batch_size=2)
    return log


@pytest.fixture
def fake_clickhouse(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub ClickHouse client."""
    fake_client = MagicMock()
    fake_client.insert = AsyncMock()
    fake_client.query = AsyncMock(return_value=[{"who": "alice"}])

    fake_mod = types.ModuleType("clickhouse_stub")
    fake_mod.get_clickhouse_client = lambda: fake_client
    monkeypatch.setitem(
        sys.modules, "src.backend.infrastructure.clients.storage.clickhouse", fake_mod
    )
    return fake_client


@pytest.fixture
def fake_correlation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub correlation helpers."""
    monkeypatch.setattr(
        "src.backend.infrastructure.audit.event_log.get_correlation_id",
        lambda: "cid-123",
    )
    monkeypatch.setattr(
        "src.backend.infrastructure.audit.event_log.get_tenant_id", lambda: "tenant-42"
    )


def test_audit_event_defaults() -> None:
    event = AuditEvent(
        who="alice",
        what="updated",
        entity_type="order",
        entity_id="ord-1",
        action="update",
    )
    assert isinstance(event.when, datetime)
    assert event.correlation_id == ""
    assert event.tenant_id == ""
    assert event.metadata == {}
    assert event.before is None
    assert event.after is None


@pytest.mark.asyncio
async def test_emit_sets_correlation_and_tenant(
    fresh_audit_log: AuditEventLog, fake_correlation: None
) -> None:
    event = AuditEvent(
        who="alice", what="x", entity_type="order", entity_id="1", action="a"
    )
    await fresh_audit_log.emit(event)
    assert event.correlation_id == "cid-123"
    assert event.tenant_id == "tenant-42"


@pytest.mark.asyncio
async def test_emit_preserves_existing_values(
    fresh_audit_log: AuditEventLog, fake_correlation: None
) -> None:
    event = AuditEvent(
        who="bob",
        what="x",
        entity_type="order",
        entity_id="1",
        action="a",
        correlation_id="existing",
        tenant_id="t1",
    )
    await fresh_audit_log.emit(event)
    assert event.correlation_id == "existing"
    assert event.tenant_id == "t1"


@pytest.mark.asyncio
async def test_flush_to_clickhouse(
    fresh_audit_log: AuditEventLog, fake_clickhouse: MagicMock, fake_correlation: None
) -> None:
    event = AuditEvent(
        who="alice",
        what="created",
        entity_type="order",
        entity_id="1",
        action="create",
        before=None,
        after={"status": "new"},
    )
    await fresh_audit_log.emit(event)
    # Since batch_size=2, first add won't flush; force flush via stop
    await fresh_audit_log.stop()
    fake_clickhouse.insert.assert_awaited_once()
    call_args = fake_clickhouse.insert.call_args
    assert call_args[0][0] == "audit_events"
    rows = call_args[0][1]
    assert len(rows) == 1
    assert rows[0]["who"] == "alice"
    assert rows[0]["after_data"] == '{"status":"new"}'


@pytest.mark.asyncio
async def test_flush_to_clickhouse_logs_error(
    fresh_audit_log: AuditEventLog,
    fake_clickhouse: MagicMock,
    fake_correlation: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_clickhouse.insert = AsyncMock(side_effect=RuntimeError("db down"))
    event = AuditEvent(
        who="alice", what="x", entity_type="order", entity_id="1", action="a"
    )
    await fresh_audit_log.emit(event)
    await fresh_audit_log.stop()
    assert "Audit flush to ClickHouse failed" in caplog.text


@pytest.mark.asyncio
async def test_query_with_filters(
    fresh_audit_log: AuditEventLog, fake_clickhouse: MagicMock
) -> None:
    result = await fresh_audit_log.query(
        entity_type="order", entity_id="1", who="alice", limit=10
    )
    assert result == [{"who": "alice"}]
    sql = fake_clickhouse.query.call_args[0][0]
    params = fake_clickhouse.query.call_args[0][1]
    assert "{entity_type:String}" in sql
    assert "{entity_id:String}" in sql
    assert "{who:String}" in sql
    assert params.get("entity_type") == "order"
    assert params.get("entity_id") == "1"
    assert params.get("who") == "alice"
    assert "LIMIT 10" in sql


@pytest.mark.asyncio
async def test_query_without_filters(
    fresh_audit_log: AuditEventLog, fake_clickhouse: MagicMock
) -> None:
    await fresh_audit_log.query()
    sql = fake_clickhouse.query.call_args[0][0]
    assert "SELECT * FROM audit_events" in sql
    assert "WHERE" not in sql


@pytest.mark.asyncio
async def test_query_invalid_table_raises() -> None:
    log = AuditEventLog(table="bad_table")
    with pytest.raises(ValueError, match="Invalid identifier"):
        await log.query()


@pytest.mark.asyncio
async def test_query_limit_bounds(
    fresh_audit_log: AuditEventLog, fake_clickhouse: MagicMock
) -> None:
    await fresh_audit_log.query(limit=5)
    assert "LIMIT 5" in fake_clickhouse.query.call_args[0][0]

    await fresh_audit_log.query(limit=999999)
    assert "LIMIT 10000" in fake_clickhouse.query.call_args[0][0]

    await fresh_audit_log.query(limit="abc")
    assert "LIMIT 100" in fake_clickhouse.query.call_args[0][0]


@pytest.mark.asyncio
async def test_query_escapes_quotes(
    fresh_audit_log: AuditEventLog, fake_clickhouse: MagicMock
) -> None:
    await fresh_audit_log.query(who="O'Brien")
    sql = fake_clickhouse.query.call_args[0][0]
    params = fake_clickhouse.query.call_args[0][1]
    assert "{who:String}" in sql
    assert params.get("who") == "O'Brien"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malicious_who",
    [
        "O'Brien",
        "'; DROP TABLE audit_events; --",
        "path\\to\\file",
        "x\\'; DROP TABLE",
        "line1\nline2",
    ],
)
async def test_query_escapes_injection_attempts(
    fresh_audit_log: AuditEventLog,
    fake_clickhouse: MagicMock,
    malicious_who: str,
) -> None:
    """S61 W4: parameterized queries protect against SQLi.

    With {name:String} bound parameters, ClickHouse handles escaping
    at the protocol level. We verify that:
    1. SQL uses {name:String} placeholders
    2. Params dict contains the raw (unescaped) malicious value
    3. The injection attempt cannot affect SQL structure
    """
    await fresh_audit_log.query(who=malicious_who)
    sql = fake_clickhouse.query.call_args[0][0]
    params = fake_clickhouse.query.call_args[0][1]
    assert "{who:String}" in sql
    assert params.get("who") == malicious_who
    # SQL must NOT contain the raw malicious string (it's in params only)
    assert malicious_who not in sql


@pytest.mark.asyncio
async def test_emit_audit_event_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    log = AuditEventLog(table="audit_events", batch_size=2)
    monkeypatch.setattr(
        "src.backend.infrastructure.audit.event_log.get_audit_log", lambda: log
    )
    emitted: list[AuditEvent] = []
    original_emit = log.emit

    async def _capture(event: AuditEvent) -> None:
        emitted.append(event)
        await original_emit(event)

    monkeypatch.setattr(log, "emit", _capture)
    await emit_audit_event(
        who="alice",
        what="created",
        entity_type="order",
        entity_id="1",
        action="create",
        before={"old": 1},
        after={"new": 2},
        source="api",
    )
    assert len(emitted) == 1
    assert emitted[0].who == "alice"
    assert emitted[0].metadata == {"source": "api"}


def test_get_audit_log_singleton() -> None:
    log1 = get_audit_log()
    log2 = get_audit_log()
    assert log1 is log2
