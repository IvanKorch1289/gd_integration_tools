"""ADR-0384 — registry-backend'ы CDC: граница батча и реальный LISTEN/NOTIFY.

Волна 16 (кластер X5, дефект 4): ``PollCDCBackend`` и
``ListenNotifyCDCBackend`` были заглушками (``if False:`` в poll-backend'е,
``wait()`` в listen/notify). Закрываем:

* poll-backend — составной курсор ``(timestamp, PK)`` (строки с одинаковым
  timestamp не теряются на границе батча) + честный статус
  ``not_implemented`` без ``sql_executor``;
* listen/notify — реальный ``asyncpg.add_listener`` с разбором payload'а.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.backend.core.utils.datetime_utils import ensure_utc
from src.backend.infrastructure.cdc.listen_notify_backend import ListenNotifyCDCBackend
from src.backend.infrastructure.cdc.poll_backend import PollCDCBackend

# ════════════════════════════════════════════════════════════════════
# 1. PollCDCBackend: граница батча
# ════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@pytest.mark.asyncio
async def test_poll_backend_does_not_lose_rows_on_batch_boundary() -> None:
    """Строки с одинаковым timestamp за пределами батча не теряются."""
    ts = datetime.now(UTC) + timedelta(hours=1)
    rows = [
        {"id": 1, "updated_at": ts},
        {"id": 2, "updated_at": ts},
        {"id": 3, "updated_at": ts},
    ]
    calls: list[str] = []

    async def fake_executor(sql: str, params: list[Any]) -> list[dict[str, Any]]:
        calls.append(sql)
        limit = int(params[-1])
        if sql.count("%s") == 4:
            # Составной курсор: (ts, PK)
            last_ts, _, last_pk, _ = params
            selected = [
                r
                for r in rows
                if ensure_utc(r["updated_at"]) > ensure_utc(last_ts)
                or (
                    ensure_utc(r["updated_at"]) == ensure_utc(last_ts)
                    and r["id"] > last_pk
                )
            ]
        else:
            # ts-only режим (PK ещё не известен): ts >= last
            last_ts = params[0]
            selected = [
                r for r in rows if ensure_utc(r["updated_at"]) >= ensure_utc(last_ts)
            ]
        selected.sort(key=lambda r: (ensure_utc(r["updated_at"]), r["id"]))
        return selected[:limit]

    backend = PollCDCBackend(
        profile="test",
        interval_s=0,
        table="events",
        batch_size=2,
        sql_executor=fake_executor,
    )

    events = []
    async for event in backend.subscribe(tables=["events"]):
        events.append(event)
        if len(events) >= 3:
            break

    got_ids = [event.new["id"] for event in events if event.new]
    assert got_ids == [1, 2, 3], f"LOST rows: {[i for i in (1, 2, 3) if i not in got_ids]}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_poll_backend_without_executor_reports_not_implemented() -> None:
    """Без ``sql_executor`` и без профиля polling-режим честно выключен."""
    backend = PollCDCBackend(profile="test", interval_s=0)

    events = [event async for event in backend.subscribe(tables=["events"])]
    assert events == []

    health = await backend.health_check()
    assert health["status"] == "not_implemented"
    assert "sql_executor" in str(health["error"])


class _FakeRow:
    """Строка результата в форме SQLAlchemy ``Row``."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._mapping = data


class _FakeResult:
    """Результат ``execute()`` внешнего engine'а."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[Any]:
        """Вернуть строки выборки."""
        return [_FakeRow(row) for row in self._rows]


class _FakeConnection:
    """Соединение внешнего engine'а."""

    def __init__(self, engine: _FakeEngine) -> None:
        self._engine = engine

    async def __aenter__(self) -> _FakeConnection:
        """Войти в контекст соединения."""
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        """Выйти из контекста соединения."""
        return False

    async def execute(self, query: Any, params: Any = None) -> _FakeResult:
        """Выполнить SELECT и зафиксировать SQL/параметры."""
        self._engine.calls.append((str(query), params))
        return _FakeResult(self._engine.rows)


class _FakeEngine:
    """Async engine внешней БД."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, Any]] = []

    def connect(self) -> _FakeConnection:
        """Вернуть fake-соединение."""
        return _FakeConnection(self)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_poll_backend_uses_profile_engine_when_no_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Registry-путь (без ``sql_executor``) работает через профиль БД.

    Иначе ``is_backend_available("poll")`` врал бы: backend был бы
    нефункциональным (ADR-0384).
    """
    ts = datetime.now(UTC) + timedelta(hours=1)
    rows = [{"id": 1, "updated_at": ts}]
    engine = _FakeEngine(rows)

    class _FakeInitializer:
        """Заглушка ``DatabaseInitializer``."""

        def get_async_engine(self) -> _FakeEngine:
            """Вернуть fake engine."""
            return engine

    class _FakeRegistry:
        """Заглушка ``ExternalDatabaseRegistry``."""

        def get_initializer(self, profile: str) -> _FakeInitializer:
            """Вернуть fake initializer."""
            return _FakeInitializer()

    monkeypatch.setattr(
        "src.backend.infrastructure.database.database.accessors."
        "get_external_db_registry",
        lambda: _FakeRegistry(),
    )

    backend = PollCDCBackend(profile="pg_prod", interval_s=0, table="events")
    events = []
    async for event in backend.subscribe(tables=["events"]):
        events.append(event)
        break

    assert len(events) == 1
    assert events[0].new == rows[0]
    assert engine.calls, "SQL was not executed through the profile engine"
    sql, params = engine.calls[0]
    assert "SELECT * FROM events" in sql
    assert ":p0" in sql
    assert isinstance(params, dict)


# ════════════════════════════════════════════════════════════════════
# 2. ListenNotifyCDCBackend: реальный listener
# ════════════════════════════════════════════════════════════════════


class _FakeAsyncpgConnection:
    """Заглушка asyncpg-соединения с emit'ом notify-payload'а."""

    def __init__(self) -> None:
        self.listeners: dict[str, Any] = {}
        self.closed = False

    async def add_listener(self, channel: str, callback: Any) -> None:
        """Зарегистрировать listener."""
        self.listeners[channel] = callback

    async def remove_listener(self, channel: str, callback: Any) -> None:
        """Снять listener."""
        self.listeners.pop(channel, None)

    async def close(self) -> None:
        """Закрыть соединение."""
        self.closed = True

    def emit(self, channel: str, payload: str) -> None:
        """Вызвать listener канала."""
        callback = self.listeners.get(channel)
        if callback is not None:
            callback(self, 1, channel, payload)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_listen_notify_subscribe_yields_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """LISTEN/NOTIFY-backend эмитит CDC-событие из notify-payload'а."""
    import asyncpg

    connection = _FakeAsyncpgConnection()

    async def _fake_connect(_dsn: str) -> _FakeAsyncpgConnection:
        return connection

    monkeypatch.setattr(asyncpg, "connect", _fake_connect)

    backend = ListenNotifyCDCBackend(
        dsn="postgresql://test:test@localhost/test", channel="cdc_orders"
    )
    generator = backend.subscribe(tables=["orders"])
    task = asyncio.create_task(generator.__anext__())
    await asyncio.sleep(0.05)

    connection.emit(
        "cdc_orders",
        json.dumps(
            {
                "operation": "INSERT",
                "table": "orders",
                "timestamp": "2026-04-19T12:00:00+00:00",
                "new": {"id": 1},
            }
        ),
    )

    event = await asyncio.wait_for(task, timeout=2.0)
    assert event.operation == "INSERT"
    assert event.table == "orders"
    assert event.new == {"id": 1}
    assert event.timestamp == datetime(2026, 4, 19, 12, 0, tzinfo=UTC)

    await backend.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_listen_notify_health_without_asyncpg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без ``asyncpg`` health сообщает «not implemented»."""
    monkeypatch.setitem(sys.modules, "asyncpg", None)

    backend = ListenNotifyCDCBackend(dsn="postgresql://test:test@localhost/test")
    health = await backend.health_check()
    assert health["status"] == "not_implemented"


# ════════════════════════════════════════════════════════════════════
# 3. Timestamp события не подменяется на now()
# ════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_client_event_keeps_datetime_timestamp() -> None:
    """ADR-0384: datetime-timestamp Kafka-события не подменяется на now()."""
    from datetime import UTC as _UTC

    from src.backend.infrastructure.cdc.cdc_client_adapter import (
        _client_event_to_source,
    )

    source_ts = datetime(2026, 4, 19, 12, 0, tzinfo=_UTC)
    event = _client_event_to_source(
        {
            "operation": "INSERT",
            "table": "orders",
            "timestamp": source_ts,
            "profile": "pg_prod",
            "new": {"id": 1},
        }
    )
    assert event.timestamp == source_ts
