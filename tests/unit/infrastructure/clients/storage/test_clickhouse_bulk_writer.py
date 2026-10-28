"""Unit-тесты ClickHouseBulkWriter (Sprint 9 K2 W2)."""

from __future__ import annotations

import asyncio

import pytest

from src.backend.infrastructure.clients.storage.clickhouse_bulk_writer import (
    ClickHouseBulkWriter,
)


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict[str, object]]]] = []
        self.fail_next = False

    async def insert(self, table: str, rows: list[dict[str, object]]) -> int:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("clickhouse down")
        self.calls.append((table, list(rows)))
        return len(rows)


@pytest.mark.asyncio
async def test_writer_flushes_by_timer() -> None:
    client = _FakeClient()
    writer = ClickHouseBulkWriter(
        client=client, table="audit", max_buffer_size=1000, flush_interval_seconds=0.05
    )
    await writer.start()
    await writer.add({"id": 1})
    await writer.add({"id": 2})
    await asyncio.sleep(0.15)
    await writer.aclose()
    # Должен быть как минимум 1 flush с 2 rows
    flushed = sum(len(rows) for _, rows in client.calls)
    assert flushed == 2


@pytest.mark.asyncio
async def test_writer_flush_now_immediate() -> None:
    client = _FakeClient()
    writer = ClickHouseBulkWriter(
        client=client,
        table="audit",
        max_buffer_size=1000,
        flush_interval_seconds=10.0,  # timer не сработает в тесте
    )
    await writer.start()
    await writer.add({"id": 1})
    await writer.add({"id": 2})
    n = await writer.flush_now()
    assert n == 2
    assert writer.stats.rows_flushed == 2
    await writer.aclose()


@pytest.mark.asyncio
async def test_writer_handles_flush_failure_via_callback() -> None:
    client = _FakeClient()
    captured: list[tuple[list[dict[str, object]], BaseException]] = []

    async def on_failure(rows: list[dict[str, object]], exc: BaseException) -> None:
        captured.append((rows, exc))

    writer = ClickHouseBulkWriter(
        client=client,
        table="audit",
        max_buffer_size=1000,
        flush_interval_seconds=10.0,
        on_failure=on_failure,
    )
    await writer.start()
    client.fail_next = True
    await writer.add({"id": 1})
    await writer.flush_now()
    await writer.aclose()
    assert len(captured) == 1
    assert isinstance(captured[0][1], RuntimeError)
    assert writer.stats.flush_failures == 1


@pytest.mark.asyncio
async def test_writer_aclose_drains_buffer() -> None:
    client = _FakeClient()
    writer = ClickHouseBulkWriter(
        client=client, table="audit", max_buffer_size=1000, flush_interval_seconds=10.0
    )
    await writer.start()
    for i in range(50):
        await writer.add({"id": i})
    await writer.aclose()
    flushed = sum(len(rows) for _, rows in client.calls)
    assert flushed == 50


@pytest.mark.asyncio
async def test_writer_add_many() -> None:
    client = _FakeClient()
    writer = ClickHouseBulkWriter(
        client=client, table="audit", max_buffer_size=10, flush_interval_seconds=10.0
    )
    await writer.start()
    await writer.add_many([{"id": i} for i in range(5)])
    await writer.flush_now()
    await writer.aclose()
    assert writer.stats.rows_flushed == 5


@pytest.mark.asyncio
async def test_writer_start_idempotent() -> None:
    client = _FakeClient()
    writer = ClickHouseBulkWriter(
        client=client, table="audit", max_buffer_size=1000, flush_interval_seconds=10.0
    )
    await writer.start()
    await writer.start()  # second call — no-op
    await writer.aclose()


# ── S-30 (Wave 13, Q18): allowlist-валидация имени таблицы ──


@pytest.mark.unit
def test_writer_rejects_injection_in_table() -> None:
    """Невалидное имя таблицы → ValueError в конструкторе, INSERT не уходит.

    Имя таблицы уходит в ``client.insert(table, rows)`` → в SQL через
    f-string. Валидируем fail-fast, до старта фонового flusher'а.
    """
    client = _FakeClient()

    with pytest.raises(ValueError, match="identifier"):
        ClickHouseBulkWriter(client=client, table="audit; DROP TABLE x")

    assert client.calls == []


@pytest.mark.asyncio
async def test_writer_accepts_valid_table() -> None:
    """Валидное имя таблицы → flush работает как раньше."""
    client = _FakeClient()
    writer = ClickHouseBulkWriter(
        client=client, table="audit_events", flush_interval_seconds=10.0
    )
    await writer.start()
    await writer.add({"id": 1})
    await writer.flush_now()
    await writer.aclose()

    assert client.calls[0][0] == "audit_events"
