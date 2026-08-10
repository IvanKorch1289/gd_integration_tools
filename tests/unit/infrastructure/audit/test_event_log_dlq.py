"""Unit-тесты AuditEventLog DLQ wiring (B-25 fix, cycle 1).

Зеркалит ``test_cdc_dlq_*`` (cycle 37, B-17):
* CDCClient._send_to_dlq → AuditEventLog._send_to_dlq;
* silent-loss устранён (events → DLQ через DLQWriter);
* production без writer'а → RuntimeError (fail-loud);
* dev_light без writer'а → log+drop;
* DLQ writer exception не пробрасывается (defense-in-depth).
"""


from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.infrastructure.audit.event_log import AuditEvent, AuditEventLog
from src.backend.infrastructure.messaging.dlq.memory_writer import InMemoryDLQWriter
from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope

# ───────────────────── Fixtures ─────────────────────


@pytest.fixture
def fresh_audit_log(monkeypatch: pytest.MonkeyPatch) -> AuditEventLog:
    """Return a fresh AuditEventLog instance and reset global singleton."""
    monkeypatch.setattr(
        "src.backend.infrastructure.audit.event_log._audit_log", None, raising=False
    )
    return AuditEventLog(table="audit_events", batch_size=2)


@pytest.fixture
def fake_clickhouse(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub ClickHouse client (insert — кастомизируется в тесте)."""
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


def _make_event(**overrides: Any) -> AuditEvent:
    """Создаёт AuditEvent с разумными defaults для тестов."""
    base: dict[str, Any] = dict(
        who="alice",
        what="x",
        entity_type="order",
        entity_id="ord-1",
        action="update",
        before={"status": "old"},
        after={"status": "new"},
    )
    base.update(overrides)
    return AuditEvent(**base)


# ───────────────────── DLQ tests (B-25 fix, cycle 1) ─────────────────────


@pytest.mark.asyncio
async def test_flush_failure_routes_events_to_dlq(
    fresh_audit_log: AuditEventLog,
    fake_clickhouse: MagicMock,
    fake_correlation: None,
) -> None:
    """B-25 fix (cycle 1): ClickHouse-failure → DLQ-writer (silent-loss устранён).

    Pre-fix: события терялись (только logger.error без routing).
    Post-fix: writer.write(envelope) вызывается для каждого event'а в batch.
    """
    fake_clickhouse.insert = AsyncMock(side_effect=RuntimeError("db down"))
    dlq = InMemoryDLQWriter()
    fresh_audit_log.set_dlq_writer(dlq)

    e1 = _make_event(entity_id="ord-A")
    e2 = _make_event(entity_id="ord-B", who="bob")
    await fresh_audit_log.emit(e1)
    await fresh_audit_log.emit(e2)
    await fresh_audit_log.stop()

    assert len(dlq.records) == 2, "all events must reach DLQ, no silent loss"
    ids = {r.original_payload["entity_id"] for r in dlq.records}
    assert ids == {"ord-A", "ord-B"}


@pytest.mark.asyncio
async def test_dlq_envelope_payload_mirrors_audit_event_fields(
    fresh_audit_log: AuditEventLog,
    fake_clickhouse: MagicMock,
    fake_correlation: None,
) -> None:
    """B-25 fix (cycle 1): DLQ envelope корректно сериализует AuditEvent.

    Проверяем:
    * transport / reason / error_class / dlq_class — стандартные поля;
    * original_payload содержит все поля AuditEvent;
    * tenant_id / trace_id — из correlation;
    * metadata передаёт table и batch_size для forensic.
    """
    fake_clickhouse.insert = AsyncMock(side_effect=RuntimeError("connection refused"))
    dlq = InMemoryDLQWriter()
    fresh_audit_log.set_dlq_writer(dlq)

    event = _make_event(
        who="carol",
        what="delete",
        entity_type="user",
        entity_id="u-777",
        action="delete",
        before={"role": "admin"},
        after=None,
        metadata={"src": "admin-panel"},
    )
    await fresh_audit_log.emit(event)
    await fresh_audit_log.stop()

    assert len(dlq.records) == 1
    env: DLQEnvelope = dlq.records[0]

    assert env.transport == "audit_event_log"
    assert env.error_class == "RuntimeError"
    assert "connection refused" in env.error_message
    assert env.reason.value == "unexpected"
    assert env.dlq_class == "operational"

    assert env.tenant_id == "tenant-42"
    assert env.trace_id == "cid-123"
    assert env.route_id == "user"

    payload = env.original_payload
    assert payload["who"] == "carol"
    assert payload["what"] == "delete"
    assert payload["entity_type"] == "user"
    assert payload["entity_id"] == "u-777"
    assert payload["action"] == "delete"
    assert payload["before"] == {"role": "admin"}
    assert payload["after"] is None
    assert payload["metadata"] == {"src": "admin-panel"}
    assert payload["correlation_id"] == "cid-123"
    assert payload["tenant_id"] == "tenant-42"
    assert "when" in payload  # isoformat string

    assert env.metadata["table"] == "audit_events"
    assert env.metadata["batch_size"] == 1


@pytest.mark.asyncio
async def test_production_no_dlq_writer_raises_runtime_error(
    fresh_audit_log: AuditEventLog,
    fake_clickhouse: MagicMock,
    fake_correlation: None,
) -> None:
    """B-25 fix (cycle 1): production без writer'а → fail-loud RuntimeError.

    Это аналог ``mark_cdc_dlq_writer_wired`` (cycle 37) — composition
    root ОБЯЗАН подключить DLQ-writer; без него silent loss НЕДОПУСТИМ.
    """
    fresh_audit_log.set_dlq_required(True)
    fresh_audit_log.set_dlq_writer(None)
    fake_clickhouse.insert = AsyncMock(side_effect=RuntimeError("boom"))

    event = _make_event()
    await fresh_audit_log.emit(event)

    with pytest.raises(RuntimeError, match="DLQ writer not wired"):
        await fresh_audit_log._flush_to_clickhouse([event])


@pytest.mark.asyncio
async def test_production_constructor_default_dlq_required_true(
    fresh_audit_log: AuditEventLog,
) -> None:
    """B-25 fix (cycle 1): default ``dlq_required=True`` (production-safe)."""
    assert fresh_audit_log._dlq_required is True
    assert fresh_audit_log._dlq_writer is None


@pytest.mark.asyncio
async def test_set_dlq_writer_overrides_post_init() -> None:
    """B-25 fix (cycle 1): setter pattern для singleton-friendly wiring.

    Composition root не имеет доступа к ``__init__`` ``get_audit_log()``
    singleton'а — wire выполняется через setter (как ``CDCClient``).
    """
    log = AuditEventLog()
    assert log._dlq_writer is None
    dlq = InMemoryDLQWriter()
    log.set_dlq_writer(dlq)
    assert log._dlq_writer is dlq
    log.set_dlq_writer(None)
    assert log._dlq_writer is None


@pytest.mark.asyncio
async def test_dev_light_no_dlq_writer_logs_and_does_not_raise(
    fresh_audit_log: AuditEventLog,
    fake_clickhouse: MagicMock,
    fake_correlation: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """B-25 fix (cycle 1): dev_light без writer'а → log+drop, НЕ raise.

    ``DLQSettings`` / dev_light профиль выставляет ``dlq_required=False``
    через :meth:`set_dlq_required`. Pre-fix поведение сохранено
    (log-and-drop) для backward-compat с dev окружениями.
    """
    fresh_audit_log.set_dlq_required(False)
    fresh_audit_log.set_dlq_writer(None)
    fake_clickhouse.insert = AsyncMock(side_effect=RuntimeError("dev mode"))

    event = _make_event()
    await fresh_audit_log.emit(event)

    # Прямой вызов — не должно поднимать RuntimeError.
    await fresh_audit_log._flush_to_clickhouse([event])

    assert "no DLQ writer configured; dropping events silently" in caplog.text
    assert "dev_light" in caplog.text


@pytest.mark.asyncio
async def test_dlq_writer_failure_does_not_propagate(
    fresh_audit_log: AuditEventLog,
    fake_clickhouse: MagicMock,
    fake_correlation: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """B-25 fix (cycle 1): DLQ writer exception → log+drop, не пробрасывается.

    Defense-in-depth: если даже DLQ-writer упал (Kafka outage, Inbox
    down), audit-middleware не должен падать. Fire-and-forget semantics
    как в ``ClickHouseAuditService._send_to_dlq``.
    """
    fake_clickhouse.insert = AsyncMock(side_effect=RuntimeError("ch down"))

    class FailingWriter:
        """DLQWriter который всегда падает."""

        async def write(self, envelope: DLQEnvelope) -> None:
            raise ConnectionError("dlq backend down")

    fresh_audit_log.set_dlq_writer(FailingWriter())  # type: ignore[arg-type]

    event = _make_event()
    await fresh_audit_log.emit(event)

    # _send_to_dlq НЕ должна пробрасывать DLQ-failure наружу.
    await fresh_audit_log._flush_to_clickhouse([event])

    assert "DLQ handoff failed" in caplog.text
    assert "EVENT WILL BE LOST" in caplog.text


@pytest.mark.asyncio
async def test_set_dlq_required_toggle(
    fresh_audit_log: AuditEventLog,
    fake_clickhouse: MagicMock,
    fake_correlation: None,
) -> None:
    """B-25 fix (cycle 1): set_dlq_required(False) отключает fail-loud guard."""
    fresh_audit_log.set_dlq_writer(None)
    fresh_audit_log.set_dlq_required(False)
    fake_clickhouse.insert = AsyncMock(side_effect=RuntimeError("test"))

    # dev_light путь — никакого RuntimeError.
    await fresh_audit_log._flush_to_clickhouse([_make_event()])

    fresh_audit_log.set_dlq_required(True)
    # production путь — RuntimeError.
    with pytest.raises(RuntimeError, match="DLQ writer not wired"):
        await fresh_audit_log._flush_to_clickhouse([_make_event()])


@pytest.mark.asyncio
async def test_dlq_envelope_succeeds_through_async_batch_path(
    fresh_audit_log: AuditEventLog,
    fake_clickhouse: MagicMock,
    fake_correlation: None,
) -> None:
    """B-25 fix (cycle 1): end-to-end через ``emit()`` + ``stop()``.

    Доказываем что DLQ-routing работает через полный AsyncBatcher
    pipeline (не только прямой вызов ``_flush_to_clickhouse``).
    Несмотря на то, что ``AsyncBatcher._do_flush`` ловит Exception,
    DLQ-writer всё равно получает envelope'ы ДО того, как исключение
    поднимется из ``_send_to_dlq``.
    """
    fake_clickhouse.insert = AsyncMock(side_effect=RuntimeError("e2e"))
    dlq = InMemoryDLQWriter()
    fresh_audit_log.set_dlq_writer(dlq)

    for i in range(3):
        await fresh_audit_log.emit(_make_event(entity_id=f"e-{i}"))

    await fresh_audit_log.stop()

    assert len(dlq.records) >= 1
    assert all(
        r.transport == "audit_event_log" for r in dlq.records
    )
