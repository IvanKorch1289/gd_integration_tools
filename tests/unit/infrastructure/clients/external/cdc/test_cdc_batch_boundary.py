"""ADR-0384 — граница батча polling-CDC и naive/aware timestamp.

Регрессии волны 16 (кластер X5):

1. **[critical] Потеря строк на границе батча.** ``WHERE ts > :last
   ORDER BY ts LIMIT n`` + курсор ``max(ts)`` → строки с одинаковым
   timestamp, не попавшие в батч, терялись навсегда (``LOST rows: [2]``).
2. **[high] PG ``timestamp without time zone`` ломает polling.** Сравнение
   aware/naive → ``TypeError: can't compare offset-naive and offset-aware
   datetimes`` → 0 событий.

Фейковая БД эмулирует семантику SQL по переданным bind-параметрам, поэтому
тесты одинаково применимы к старой (``last``/``>``) и новой (``last_ts``/
``last_pk``) реализации.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.backend.core.utils.datetime_utils import ensure_utc
from src.backend.infrastructure.clients.external.cdc.events import (
    CDCEvent,
    CDCSubscription,
)
from src.backend.infrastructure.clients.external.cdc.strategies import _PollingStrategy

# ════════════════════════════════════════════════════════════════════
# Fakes
# ════════════════════════════════════════════════════════════════════


class _Row:
    """Строка результата в форме SQLAlchemy ``Row``."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._mapping = data


class _FakeResult:
    """Результат ``execute()``."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[_Row]:
        """Вернуть строки результата."""
        return [_Row(r) for r in self._rows]


class _FakeTable:
    """Эмуляция таблицы: фильтрация по timestamp/PK + сортировка + LIMIT."""

    def __init__(
        self,
        rows: list[dict[str, Any]],
        *,
        ts_column: str = "updated_at",
        pk_column: str = "id",
    ) -> None:
        self.rows = rows
        self.ts_column = ts_column
        self.pk_column = pk_column
        self.queries: list[dict[str, Any]] = []
        self.max_queries = 8

    def select(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Выполнить SELECT по семантике переданных bind-параметров."""
        self.queries.append(dict(params))
        limit = int(params.get("limit", len(self.rows) or 1))
        last = params.get("last_ts", params.get("last"))
        last_pk = params.get("last_pk")

        selected: list[dict[str, Any]] = []
        for row in self.rows:
            ts = ensure_utc(row[self.ts_column])
            if last is not None:
                last_aware = ensure_utc(last)
                if last_pk is not None:
                    # Составной курсор (ts, PK): ts > last OR (ts == last AND pk > last_pk)
                    if not (
                        ts > last_aware
                        or (ts == last_aware and row[self.pk_column] > last_pk)
                    ):
                        continue
                elif "last_ts" in params:
                    # ts-only режим с >= (PK ещё не известен) — строки не теряются.
                    if ts < last_aware:
                        continue
                else:
                    # Legacy-режим (ts > last) — именно он терял строки.
                    if ts <= last_aware:
                        continue
            selected.append(row)

        selected.sort(key=lambda r: (ensure_utc(r[self.ts_column]), r[self.pk_column]))
        return selected[:limit]


class _FakeConnection:
    """Соединение, перехватывающее SQL polling-стратегии."""

    def __init__(self, table: _FakeTable, sub: CDCSubscription) -> None:
        self._table = table
        self._sub = sub

    async def __aenter__(self) -> _FakeConnection:
        """Войти в контекст соединения."""
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        """Выйти из контекста соединения."""
        return False

    async def execute(self, query: Any, params: Any = None) -> _FakeResult:
        """Выполнить SELECT и остановить polling-цикл после N запросов."""
        rows = self._table.select(dict(params or {}))
        if len(self._table.queries) >= self._table.max_queries:
            self._sub.active = False
        return _FakeResult(rows)


class _FakeEngine:
    """Async engine, отдающий fake-соединения."""

    def __init__(self, table: _FakeTable, sub: CDCSubscription) -> None:
        self._table = table
        self._sub = sub

    def connect(self) -> _FakeConnection:
        """Вернуть новое fake-соединение."""
        return _FakeConnection(self._table, self._sub)


class _FakeInitializer:
    """Заглушка ``DatabaseInitializer``."""

    def __init__(self, engine: _FakeEngine) -> None:
        self._engine = engine

    def get_async_engine(self) -> _FakeEngine:
        """Вернуть fake async engine."""
        return self._engine


class _FakeRegistry:
    """Заглушка ``ExternalDatabaseRegistry``."""

    def __init__(self, engine: _FakeEngine) -> None:
        self._engine = engine

    def get_initializer(self, profile: str) -> _FakeInitializer:
        """Вернуть fake initializer."""
        return _FakeInitializer(self._engine)


class _FakeRedisCursor:
    """In-memory замена ``RedisCursor`` (CAS по lexicographic)."""

    store: dict[str, str] = {}

    def __init__(self, key: str) -> None:
        self._key = key

    async def get_or_init(self, default: str) -> str:
        """Вернуть текущее значение курсора или инициализировать."""
        return self.store.setdefault(self._key, default)

    async def try_advance(self, new_value: str) -> bool:
        """Атомарно продвинуть курсор, если новое значение больше."""
        current = self.store.get(self._key)
        if current is None or new_value > current:
            self.store[self._key] = new_value
            return True
        return False


# ════════════════════════════════════════════════════════════════════
# Fixtures / helpers
# ════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _fake_redis_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подменить Redis-курсор на in-memory (без внешних зависимостей)."""
    _FakeRedisCursor.store = {}
    monkeypatch.setattr(
        "src.backend.infrastructure.clients.storage.redis_coordinator.RedisCursor",
        _FakeRedisCursor,
    )


def _install_registry(
    monkeypatch: pytest.MonkeyPatch, table: _FakeTable, sub: CDCSubscription
) -> None:
    """Подменить реестр внешних БД на fake с нужной таблицей."""
    engine = _FakeEngine(table, sub)
    registry = _FakeRegistry(engine)
    monkeypatch.setattr(
        "src.backend.infrastructure.database.database.accessors."
        "get_external_db_registry",
        lambda: registry,
    )


async def _run_polling(
    sub: CDCSubscription,
) -> list[CDCEvent]:
    """Прогнать polling-стратегию и собрать все события."""
    events: list[CDCEvent] = []

    async def _dispatch(_sub: CDCSubscription, event: CDCEvent) -> None:
        events.append(event)

    strategy = _PollingStrategy()
    await strategy.run(sub, _dispatch)
    return events


# ════════════════════════════════════════════════════════════════════
# 1. Граница батча: строки с одинаковым timestamp не теряются
# ════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@pytest.mark.asyncio
async def test_polling_does_not_lose_rows_on_batch_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Строки с одинаковым ts за пределами батча не теряются.

    Классический дефект: ``WHERE ts > :last`` + курсор ``max(ts)`` →
    вторая строка с тем же ts, что и последняя в батче, пропадала навсегда.
    """
    ts = datetime.now(UTC) + timedelta(hours=1)
    rows = [
        {"id": 1, "updated_at": ts},
        {"id": 2, "updated_at": ts},
        {"id": 3, "updated_at": ts},
    ]
    table = _FakeTable(rows)
    table.max_queries = 8

    sub = CDCSubscription(
        profile="pg_prod",
        tables=["events"],
        interval=0,
        batch_size=2,
        primary_key="id",
    )
    _install_registry(monkeypatch, table, sub)

    events = await _run_polling(sub)

    got_ids = [event.new["id"] for event in events if event.new]
    assert got_ids == [1, 2, 3], f"LOST rows: {[i for i in (1, 2, 3) if i not in got_ids]}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_polling_detects_primary_key_without_explicit_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PK определяется по первой выборке — строки не теряются и без явного PK."""
    ts = datetime.now(UTC) + timedelta(hours=1)
    rows = [
        {"id": 1, "updated_at": ts},
        {"id": 2, "updated_at": ts},
        {"id": 3, "updated_at": ts},
    ]
    table = _FakeTable(rows)
    table.max_queries = 8

    sub = CDCSubscription(
        profile="pg_prod",
        tables=["events"],
        interval=0,
        batch_size=2,
    )
    _install_registry(monkeypatch, table, sub)

    events = await _run_polling(sub)

    got_ids = [event.new["id"] for event in events if event.new]
    assert got_ids == [1, 2, 3]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_polling_emits_no_duplicates_across_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Повторное чтение границы батча не приводит к дублям событий."""
    ts = datetime.now(UTC) + timedelta(hours=1)
    rows = [
        {"id": 1, "updated_at": ts},
        {"id": 2, "updated_at": ts},
        {"id": 3, "updated_at": ts},
    ]
    table = _FakeTable(rows)
    table.max_queries = 8

    sub = CDCSubscription(
        profile="pg_prod",
        tables=["events"],
        interval=0,
        batch_size=2,
        primary_key="id",
    )
    _install_registry(monkeypatch, table, sub)

    events = await _run_polling(sub)

    got_ids = [event.new["id"] for event in events if event.new]
    assert len(got_ids) == len(set(got_ids)), f"duplicate events: {got_ids}"


# ════════════════════════════════════════════════════════════════════
# 2. naive timestamp (PG timestamp without time zone)
# ════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@pytest.mark.asyncio
async def test_polling_handles_naive_timestamp_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Naive datetime из ``timestamp without time zone`` не ломает polling."""
    naive_ts = (datetime.now(UTC) + timedelta(hours=1)).replace(tzinfo=None)
    rows = [{"id": 1, "updated_at": naive_ts}]
    table = _FakeTable(rows)
    table.max_queries = 4

    sub = CDCSubscription(
        profile="pg_prod",
        tables=["events"],
        interval=0,
        batch_size=10,
        primary_key="id",
    )
    _install_registry(monkeypatch, table, sub)

    events = await _run_polling(sub)

    assert len(events) == 1, "naive timestamp produced 0 events (aware/naive TypeError)"
    assert events[0].timestamp is not None
    assert events[0].new == {"id": 1, "updated_at": naive_ts}
