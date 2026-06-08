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
    assert "entity_type = 'order'" in sql
    assert "entity_id = '1'" in sql
    assert "who = 'alice'" in sql
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
    assert "O''Brien" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("malicious_who", "expected_substring"),
    [
        # classic quote-escape (already covered, but parametrized for clarity)
        ("O'Brien", "O''Brien"),
        # single quote injection attempt — must be escaped, never terminated.
        # Input `'; DROP TABLE ...` (1 quote) → escaped `''; DROP TABLE ...` (2 quotes).
        ("'; DROP TABLE audit_events; --", "''; DROP TABLE audit_events; --"),
        # backslash injection — ClickHouse treats \ as escape in strings
        ("path\\to\\file", "path\\\\to\\\\file"),
        # combined: backslash-then-quote (worst case)
        ("x\\'; DROP TABLE", "x\\\\''; DROP TABLE"),
        # newline / control char — passed through, _escape doesn't strip
        ("line1\nline2", "line1\nline2"),
    ],
)
async def test_query_escapes_injection_attempts(
    fresh_audit_log: AuditEventLog,
    fake_clickhouse: MagicMock,
    malicious_who: str,
    expected_substring: str,
) -> None:
    """S61 W4: defense-in-depth — _escape must neutralize classic SQLi vectors.

    Note: this is NOT parameterized query protection. ClickHouse HTTP API
    does not support `?` placeholders in SELECT; parametrization would
    require {name:Type} syntax + client.get(..., params={...}) and is
    out of scope for a single query() method. Defense layers:
    1. _safe_ident allowlist (table name) — ValueError on unknown.
    2. _escape (single quote → double, backslash → double).
    3. safe_limit int-bounded.
    All string values flow through _escape; verify here that injection
    attempts cannot terminate the string literal.
    """
    await fresh_audit_log.query(who=malicious_who)
    sql = fake_clickhouse.query.call_args[0][0]
    assert expected_substring in sql
    # Sanity: `who = '...'` literal must contain an even number of single
    # quotes (escaped pairs + closing). If `_escape` ever forgot to double
    # a quote, the literal would terminate early → odd count.
    start = sql.find("who = '")
    assert start >= 0, f"who clause not found in SQL: {sql!r}"
    end = sql.find("' ORDER BY", start)
    assert end > start, f"closing quote not found: {sql!r}"
    inner = sql[start + len("who = '") : end]
    assert inner.count("'") % 2 == 0, f"Odd quote count in literal: {inner!r}"


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
