"""Integration-тесты CdcPostgresLogicalSource (P4.20, WAVE 2).

End-to-end сценарий поверх in-process fake-postgres (asyncpg-совместимый
session-factory + подменённый низкоуровневый ``CDCSource``): реальный
postgres/testgres в CI недоступен, поэтому проверяется полный цикл
setup → tail → watermark-ack → resume → stop без сети.

Покрытие (то, чего нет в unit-suite):
    * idempotent ``setup`` дважды (publication/slot уже существуют);
    * watermark-cursor реально сохраняется в ``cdc_cursors`` при tail;
    * resume после restart читает сохранённый LSN;
    * ``stop`` освобождает inner source, ``health`` до старта = failed.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.core.interfaces.source import EventCallback, SourceEvent, SourceKind
from src.backend.infrastructure.sources.cdc_postgres_logical import (
    CdcCursorStore,
    CdcPostgresLogicalSource,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class _FakePostgres:
    """Минимальная in-process эмуляция postgres для CDC-таблиц.

    ponytail: только то, что использует ``CdcCursorStore`` — DDL-учёт,
    upsert и одиночный ``fetchrow``. Не SQL-парсер.
    """

    def __init__(self) -> None:
        self.ddl: list[str] = []
        self.cursors: dict[str, str] = {}
        self.tables: set[str] = set()

    async def execute(self, sql: str, *args: object) -> None:
        """Выполнить DDL/DML (упрощённая маршрутизация по подстроке)."""
        norm = " ".join(sql.split())
        if "CREATE TABLE IF NOT EXISTS cdc_cursors" in norm:
            self.ddl.append(norm)
            self.tables.add("cdc_cursors")
            return
        if norm.startswith("CREATE PUBLICATION"):
            if norm in self.ddl:
                raise RuntimeError("publication already exists")
            self.ddl.append(norm)
            return
        if "pg_create_logical_replication_slot" in norm:
            if norm in self.ddl:
                raise RuntimeError("replication slot already exists")
            self.ddl.append(norm)
            return
        if "INSERT INTO cdc_cursors" in norm:
            if "cdc_cursors" not in self.tables:
                raise RuntimeError('relation "cdc_cursors" does not exist')
            self.cursors[str(args[0])] = str(args[1])
            return
        raise AssertionError(f"unexpected SQL: {norm}")

    async def fetchrow(self, sql: str, *args: object) -> dict[str, str] | None:
        """Вернуть строку курсора по slot_name либо ``None``."""
        slot = str(args[0])
        if slot in self.cursors:
            return {"last_lsn": self.cursors[slot]}
        return None

    def session_factory(self) -> Any:
        """Async-context-manager factory в стиле asyncpg-pool.acquire()."""

        @asynccontextmanager
        async def _factory() -> Any:
            yield self

        return _factory


class _FakeInnerCdc:
    """Подмена низкоуровневого ``CDCSource`` — эмитит заданные WAL-события."""

    events: list[dict[str, Any]] = []
    started: int = 0
    stopped: int = 0

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    async def start(self, on_event: EventCallback) -> None:
        """Проиграть заранее заданный WAL-стрим."""
        type(self).started += 1
        for payload in type(self).events:
            await on_event(
                SourceEvent(
                    source_id=self.kwargs["source_id"],
                    kind=SourceKind.CDC,
                    payload=payload,
                    event_time=datetime.now(UTC),
                    metadata={"slot": self.kwargs["slot_name"]},
                )
            )

    async def stop(self) -> None:
        """Зафиксировать вызов stop."""
        type(self).stopped += 1


@pytest.fixture
def pg() -> _FakePostgres:
    """In-process fake-postgres на тест."""
    return _FakePostgres()


@pytest.fixture
def inner(monkeypatch: pytest.MonkeyPatch) -> type[_FakeInnerCdc]:
    """Подменить ``CDCSource`` на fake и сбросить счётчики."""
    _FakeInnerCdc.events = []
    _FakeInnerCdc.started = 0
    _FakeInnerCdc.stopped = 0
    monkeypatch.setattr(
        "src.backend.infrastructure.sources.cdc.CDCSource", _FakeInnerCdc
    )
    monkeypatch.setattr(feature_flags, "cdc_postgres_enabled", True)
    return _FakeInnerCdc


def _make_source(pg: _FakePostgres, *, mode: str = "delta") -> CdcPostgresLogicalSource:
    return CdcPostgresLogicalSource(
        "orders-cdc",
        "orders",
        dsn="postgresql://localhost/test",
        mode=mode,
        cursor_store=CdcCursorStore(pg.session_factory()),
    )


async def test_setup_idempotent(pg: _FakePostgres) -> None:
    """Повторный setup не падает: publication/slot уже существуют."""
    src = _make_source(pg)
    await src.setup(pg.execute)
    await src.setup(pg.execute)

    assert "cdc_cursors" in pg.tables
    assert sum(1 for s in pg.ddl if s.startswith("CREATE PUBLICATION")) == 1
    assert sum(1 for s in pg.ddl if "replication_slot" in s) == 1


async def test_tail_persists_watermark_and_resumes(
    pg: _FakePostgres, inner: type[_FakeInnerCdc]
) -> None:
    """Tail сохраняет last_lsn, после restart он доступен для resume."""
    inner.events = [
        {"op": "INSERT", "lsn": "0/16D5E40", "row": {"id": 1}},
        {"op": "UPDATE", "lsn": "0/16D5F10", "row": {"id": 1}},
    ]
    src = _make_source(pg)
    await src.setup(pg.execute)

    received: list[SourceEvent] = []
    await src.start(_collect(received))
    await src.stop()

    assert [e.payload["op"] for e in received] == ["INSERT", "UPDATE"]
    assert pg.cursors[src.slot_name] == "0/16D5F10"
    assert inner.stopped == 1

    resumed = _make_source(pg)
    assert (
        await resumed.cursor_store.get_last_lsn(resumed.slot_name) == "0/16D5F10"
        if resumed.cursor_store
        else False
    )


async def test_full_mode_marker_precedes_tail(
    pg: _FakePostgres, inner: type[_FakeInnerCdc]
) -> None:
    """В режиме ``full`` snapshot-маркер приходит до WAL-событий."""
    inner.events = [{"op": "INSERT", "lsn": "0/1", "row": {"id": 7}}]
    src = _make_source(pg, mode="full")
    await src.setup(pg.execute)

    received: list[SourceEvent] = []
    await src.start(_collect(received))

    assert received[0].payload == {"event": "snapshot_started", "table": "orders"}
    assert received[1].payload["op"] == "INSERT"


async def test_health_failed_before_start(pg: _FakePostgres) -> None:
    """До ``start`` health = failed (inner source отсутствует)."""
    src = _make_source(pg)
    result = await src.health()
    assert result.status == "failed"
    assert result.error == "Not started"


async def test_cursor_write_failure_does_not_break_stream(
    pg: _FakePostgres, inner: type[_FakeInnerCdc]
) -> None:
    """Ошибка записи watermark не прерывает поток событий (at-least-once)."""
    inner.events = [{"op": "INSERT", "lsn": "0/2", "row": {"id": 1}}]
    src = _make_source(pg)
    # setup НЕ вызван → cdc_cursors отсутствует → upsert упадёт.
    received: list[SourceEvent] = []
    await src.start(_collect(received))

    assert len(received) == 1
    assert pg.cursors == {}


def _collect(sink: list[SourceEvent]) -> EventCallback:
    async def _on_event(event: SourceEvent) -> None:
        sink.append(event)

    return _on_event
