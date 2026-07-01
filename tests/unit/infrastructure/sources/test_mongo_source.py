"""S107 W5 — unit-тесты MongoSource (real runtime).

Покрывают:

* валидацию MongoSourceConfig (connection_url, database, reconnect params);
* эмиссию MongoChangeEvent через async iterator (mock motor.watch);
* resume-token state (сохранение между event'ами);
* reconnect-loop при ошибке подключения;
* graceful ImportError при отсутствии motor;
* start() callback-обёртку (Source-контракт);
* stop() и health() liveness-проверки.

Сетевая часть (реальное подключение к MongoDB) НЕ тестируется —
только логика через mock motor.
"""

# ruff: noqa: S101, I001

from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.infrastructure.sources.mongo import (
    MongoChangeEvent,
    MongoSource,
    MongoSourceConfig,
)


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательные фабрики


def _make_fake_change_event(
    operation: str = "insert",
    doc_id: str = "abc123",
    full_doc: dict | None = None,
    resume_token: dict | None = None,
    coll: str = "orders",
) -> dict:
    """Создаёт mock Mongo change-event (raw dict как приходит из motor)."""
    return {
        "operationType": operation,
        "ns": {"db": "test_db", "coll": coll},
        "documentKey": {"_id": doc_id},
        "fullDocument": full_doc or {"_id": doc_id, "status": "created"},
        "_id": resume_token or {"_data": "token-1"},
    }


def _install_fake_motor(
    monkeypatch: pytest.MonkeyPatch,
    events: list[dict],
    *,
    client_raises: Exception | None = None,
    client_call_count: list[int] | None = None,
) -> None:
    """Устанавливает fake motor module в sys.modules.

    Имитирует: ``AsyncIOMotorClient(url)`` → ``client`` → ``client[db]`` →
    ``db.watch()`` → change-stream с ``.next()`` и ``.close()``.
    """
    if client_call_count is None:
        client_call_count = [0]

    event_iter = iter(events)

    change_stream = MagicMock()
    change_stream.close = AsyncMock()

    async def _next():
        try:
            return next(event_iter)
        except StopIteration:
            return None

    change_stream.next = _next

    coll = MagicMock()
    coll.watch = MagicMock(return_value=change_stream)

    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=coll)
    db.watch = MagicMock(return_value=change_stream)

    admin = MagicMock()
    admin.command = AsyncMock(return_value={"ok": 1.0})

    client = MagicMock()
    client.__getitem__ = MagicMock(return_value=db)
    client.admin = admin
    client.close = MagicMock()

    def _client_factory(*args, **kwargs):
        client_call_count[0] += 1
        if client_raises is not None:
            raise client_raises
        return client

    fake_motor = types.ModuleType("motor")
    fake_motor_asyncio = types.ModuleType("motor.motor_asyncio")
    fake_motor_asyncio.AsyncIOMotorClient = _client_factory  # type: ignore[attr-defined]
    fake_motor.motor_asyncio = fake_motor_asyncio  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "motor", fake_motor)
    monkeypatch.setitem(sys.modules, "motor.motor_asyncio", fake_motor_asyncio)


def _install_fake_motor_with_full_control(
    monkeypatch: pytest.MonkeyPatch, change_stream_factory
) -> None:
    """Устанавливает fake motor с настраиваемой change-stream factory.

    Args:
        change_stream_factory: callable(db_mock) -> change_stream_mock
    """
    admin = MagicMock()
    admin.command = AsyncMock(return_value={"ok": 1.0})

    client = MagicMock()
    client.admin = admin
    client.close = MagicMock()

    def _client_factory(*args, **kwargs):
        return client

    fake_motor = types.ModuleType("motor")
    fake_motor_asyncio = types.ModuleType("motor.motor_asyncio")
    fake_motor_asyncio.AsyncIOMotorClient = _client_factory  # type: ignore[attr-defined]
    fake_motor.motor_asyncio = fake_motor_asyncio  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "motor", fake_motor)
    monkeypatch.setitem(sys.modules, "motor.motor_asyncio", fake_motor_asyncio)


# ──────────────────────────────────────────────────────────────────────────────
# Тесты — validation


def test_construction_validates_connection_url() -> None:
    """Пустой connection_url → ValueError."""
    with pytest.raises(ValueError, match="connection_url обязателен"):
        MongoSource(MongoSourceConfig(connection_url="", database="db1"))


def test_construction_validates_database() -> None:
    """Пустой database → ValueError."""
    with pytest.raises(ValueError, match="database обязателен"):
        MongoSource(
            MongoSourceConfig(connection_url="mongodb://localhost", database="")
        )


def test_construction_validates_reconnect_params() -> None:
    """max_reconnect_attempts < 0 → ValueError, delay < 0 → ValueError."""
    with pytest.raises(ValueError, match="max_reconnect_attempts"):
        MongoSource(
            MongoSourceConfig(
                connection_url="mongodb://localhost",
                database="db1",
                max_reconnect_attempts=-1,
            )
        )
    with pytest.raises(ValueError, match="reconnect_delay_seconds"):
        MongoSource(
            MongoSourceConfig(
                connection_url="mongodb://localhost",
                database="db1",
                reconnect_delay_seconds=-0.5,
            )
        )


def test_source_id_format() -> None:
    """source_id включает db + coll (или * если пустая)."""
    src1 = MongoSource(
        MongoSourceConfig(
            connection_url="mongodb://localhost", database="db1", collection="orders"
        )
    )
    assert src1.source_id == "mongo:db1/orders"

    src2 = MongoSource(
        MongoSourceConfig(
            connection_url="mongodb://localhost", database="db1", collection=""
        )
    )
    assert src2.source_id == "mongo:db1/*"


def test_kind_is_cdc() -> None:
    """SourceKind.CDC для MongoDB change-streams."""
    src = MongoSource(
        MongoSourceConfig(connection_url="mongodb://localhost", database="db1")
    )
    assert src.kind.value == "cdc"


def test_resume_token_initially_none() -> None:
    """resume_token = None до первого event'а."""
    src = MongoSource(
        MongoSourceConfig(connection_url="mongodb://localhost", database="db1")
    )
    assert src.resume_token is None


# ──────────────────────────────────────────────────────────────────────────────
# Тесты — stream() runtime


@pytest.mark.asyncio
async def test_stream_emits_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """MongoSource.stream() эмитит MongoChangeEvent для каждого change."""
    events = [
        _make_fake_change_event(
            operation="insert", doc_id="doc-1", resume_token={"_data": "tok-1"}
        ),
        _make_fake_change_event(
            operation="update", doc_id="doc-1", resume_token={"_data": "tok-2"}
        ),
    ]
    _install_fake_motor(monkeypatch, events)

    src = MongoSource(
        MongoSourceConfig(
            connection_url="mongodb://localhost", database="db1", collection="orders"
        )
    )

    received: list[MongoChangeEvent] = []
    async for ev in src.stream():
        received.append(ev)
        if len(received) >= 2:
            break

    assert len(received) == 2
    assert received[0].operation_type == "insert"
    assert received[0].document_key == {"_id": "doc-1"}
    assert received[0].full_document == {"_id": "doc-1", "status": "created"}
    assert received[0].resume_token == {"_data": "tok-1"}
    assert isinstance(received[0].timestamp, datetime)
    assert received[1].operation_type == "update"


@pytest.mark.asyncio
async def test_stream_saves_resume_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """После yield первого event'а _resume_token сохранён в src."""
    events = [_make_fake_change_event(resume_token={"_data": "tok-99"})]
    _install_fake_motor(monkeypatch, events)

    src = MongoSource(
        MongoSourceConfig(connection_url="mongodb://localhost", database="db1")
    )

    assert src.resume_token is None
    async for ev in src.stream():
        # Первый (и единственный) event
        assert ev.resume_token == {"_data": "tok-99"}
        assert src.resume_token == {"_data": "tok-99"}
        break


@pytest.mark.asyncio
async def test_stream_passes_resume_token_to_watch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При resume_token != None → coll.watch(resume_after=...) используется."""
    cfg = MongoSourceConfig(
        connection_url="mongodb://localhost", database="db1", collection="orders"
    )
    src = MongoSource(cfg)
    src._resume_token = {"_data": "saved-tok"}

    watch_calls: list[dict] = []
    change_stream = MagicMock()
    change_stream.close = AsyncMock()

    async def _next():
        return None  # сразу закрываем

    change_stream.next = _next

    def _watch(**kwargs):
        watch_calls.append(kwargs)
        return change_stream

    coll = MagicMock()
    coll.watch = MagicMock(side_effect=_watch)
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=coll)
    admin = MagicMock()
    admin.command = AsyncMock(return_value={"ok": 1.0})
    client = MagicMock()
    client.__getitem__ = MagicMock(return_value=db)
    client.admin = admin
    client.close = MagicMock()

    def _client_factory(*args, **kwargs):
        return client

    fake_motor = types.ModuleType("motor")
    fake_motor_asyncio = types.ModuleType("motor.motor_asyncio")
    fake_motor_asyncio.AsyncIOMotorClient = _client_factory  # type: ignore[attr-defined]
    fake_motor.motor_asyncio = fake_motor_asyncio  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "motor", fake_motor)
    monkeypatch.setitem(sys.modules, "motor.motor_asyncio", fake_motor_asyncio)

    async for _ in src.stream():
        pass

    assert len(watch_calls) == 1
    assert watch_calls[0].get("resume_after") == {"_data": "saved-tok"}


@pytest.mark.asyncio
async def test_stream_db_level_watch(monkeypatch: pytest.MonkeyPatch) -> None:
    """При пустой collection → db.watch() (не coll.watch)."""
    events = [_make_fake_change_event()]
    _install_fake_motor(monkeypatch, events)

    src = MongoSource(
        MongoSourceConfig(
            connection_url="mongodb://localhost", database="db1", collection=""
        )
    )

    # Просто smoke: stream завершается без падения
    async for ev in src.stream():
        assert ev.operation_type == "insert"
        break


@pytest.mark.asyncio
async def test_stream_full_document_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """full_document_lookup=True → watch(full_document=updateLookup)."""
    cfg = MongoSourceConfig(
        connection_url="mongodb://localhost",
        database="db1",
        collection="orders",
        full_document_lookup=True,
    )
    src = MongoSource(cfg)

    watch_calls: list[dict] = []
    change_stream = MagicMock()
    change_stream.close = AsyncMock()

    async def _next():
        return None

    change_stream.next = _next

    coll = MagicMock()

    def _watch(**kwargs):
        watch_calls.append(kwargs)
        return change_stream

    coll.watch = MagicMock(side_effect=_watch)
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=coll)
    admin = MagicMock()
    admin.command = AsyncMock(return_value={"ok": 1.0})
    client = MagicMock()
    client.__getitem__ = MagicMock(return_value=db)
    client.admin = admin
    client.close = MagicMock()

    def _client_factory(*args, **kwargs):
        return client

    fake_motor = types.ModuleType("motor")
    fake_motor_asyncio = types.ModuleType("motor.motor_asyncio")
    fake_motor_asyncio.AsyncIOMotorClient = _client_factory  # type: ignore[attr-defined]
    fake_motor.motor_asyncio = fake_motor_asyncio  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "motor", fake_motor)
    monkeypatch.setitem(sys.modules, "motor.motor_asyncio", fake_motor_asyncio)

    async for _ in src.stream():
        pass

    assert len(watch_calls) == 1
    assert watch_calls[0].get("full_document") == "updateLookup"


@pytest.mark.asyncio
async def test_stream_import_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """При отсутствии motor stream() немедленно поднимает ImportError."""
    monkeypatch.delitem(sys.modules, "motor", raising=False)
    monkeypatch.delitem(sys.modules, "motor.motor_asyncio", raising=False)

    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "motor" or name.startswith("motor."):
            raise ImportError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    src = MongoSource(
        MongoSourceConfig(connection_url="mongodb://localhost", database="db1")
    )

    with pytest.raises(ImportError, match="motor not installed"):
        async for _ in src.stream():
            pass  # pragma: no cover


@pytest.mark.asyncio
async def test_stream_reconnect_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    """При постоянной ошибке client → RuntimeError после max_attempts."""
    _install_fake_motor(
        monkeypatch, [], client_raises=ConnectionError("mongo unreachable")
    )

    src = MongoSource(
        MongoSourceConfig(
            connection_url="mongodb://localhost",
            database="db1",
            max_reconnect_attempts=2,
            reconnect_delay_seconds=0.01,
        )
    )

    with pytest.raises(RuntimeError, match="max reconnect attempts"):
        async for _ in src.stream():
            pass  # pragma: no cover


@pytest.mark.asyncio
async def test_stream_reconnects_after_initial_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Первый client fails, второй succeeds → event эмитируется."""
    client_calls = [0]

    def _client_factory(*args, **kwargs):
        client_calls[0] += 1
        if client_calls[0] == 1:
            raise ConnectionError("transient")

        # Second call: success
        change_stream = MagicMock()
        change_stream.close = AsyncMock()
        change_stream.next = AsyncMock(
            side_effect=[
                _make_fake_change_event(
                    doc_id="after-reconnect", resume_token={"_data": "tok-r"}
                ),
                None,
            ]
        )
        coll = MagicMock()
        coll.watch = MagicMock(return_value=change_stream)
        db = MagicMock()
        db.__getitem__ = MagicMock(return_value=coll)
        admin = MagicMock()
        admin.command = AsyncMock(return_value={"ok": 1.0})
        client = MagicMock()
        client.__getitem__ = MagicMock(return_value=db)
        client.admin = admin
        client.close = MagicMock()
        return client

    fake_motor = types.ModuleType("motor")
    fake_motor_asyncio = types.ModuleType("motor.motor_asyncio")
    fake_motor_asyncio.AsyncIOMotorClient = _client_factory  # type: ignore[attr-defined]
    fake_motor.motor_asyncio = fake_motor_asyncio  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "motor", fake_motor)
    monkeypatch.setitem(sys.modules, "motor.motor_asyncio", fake_motor_asyncio)

    src = MongoSource(
        MongoSourceConfig(
            connection_url="mongodb://localhost",
            database="db1",
            collection="orders",
            max_reconnect_attempts=3,
            reconnect_delay_seconds=0.01,
        )
    )

    received: list[MongoChangeEvent] = []
    async for ev in src.stream():
        received.append(ev)
        break

    assert client_calls[0] == 2
    assert len(received) == 1
    assert received[0].document_key == {"_id": "after-reconnect"}


# ──────────────────────────────────────────────────────────────────────────────
# Тесты — start() / stop() / health()


@pytest.mark.asyncio
async def test_start_invokes_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    """start() оборачивает stream() и эмитит SourceEvent через callback."""
    events = [_make_fake_change_event(doc_id="x")]
    _install_fake_motor(monkeypatch, events)

    src = MongoSource(
        MongoSourceConfig(
            connection_url="mongodb://localhost", database="shop", collection="orders"
        )
    )

    received_events: list = []

    async def on_event(ev):
        received_events.append(ev)
        src._running = False

    on_event_mock = AsyncMock(side_effect=on_event)

    task = asyncio.create_task(src.start(on_event_mock))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if received_events:
            break

    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    assert len(received_events) >= 1
    assert received_events[0].source_id == "mongo:shop/orders"
    assert received_events[0].kind.value == "cdc"
    assert received_events[0].metadata["operation_type"] == "insert"


@pytest.mark.asyncio
async def test_stop_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """stop() можно вызывать многократно без ошибок."""
    _install_fake_motor(monkeypatch, [])

    src = MongoSource(
        MongoSourceConfig(connection_url="mongodb://localhost", database="db1")
    )
    await src.stop()
    await src.stop()
    assert src._running is False
    assert src._client is None


@pytest.mark.asyncio
async def test_health_initially_false() -> None:
    """health() == False до запуска stream()."""
    src = MongoSource(
        MongoSourceConfig(connection_url="mongodb://localhost", database="db1")
    )
    assert await src.health() is False


@pytest.mark.asyncio
async def test_health_ping_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """health() == True если client.ping() успешен."""
    _install_fake_motor(monkeypatch, [])

    src = MongoSource(
        MongoSourceConfig(connection_url="mongodb://localhost", database="db1")
    )

    fake_client = MagicMock()
    fake_client.admin.command = AsyncMock(return_value={"ok": 1.0})
    src._client = fake_client

    assert await src.health() is True


@pytest.mark.asyncio
async def test_health_ping_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """health() == False если client.ping() падает."""
    src = MongoSource(
        MongoSourceConfig(connection_url="mongodb://localhost", database="db1")
    )

    fake_client = MagicMock()
    fake_client.admin.command = AsyncMock(side_effect=ConnectionError("mongo down"))
    src._client = fake_client

    assert await src.health() is False


@pytest.mark.asyncio
async def test_mongochangeevent_defaults() -> None:
    """MongoChangeEvent c минимальными полями — дефолты работают."""
    ev = MongoChangeEvent(operation_type="insert", database="db1", collection="orders")
    assert ev.document_key is None
    assert ev.full_document is None
    assert ev.resume_token is None
    assert isinstance(ev.timestamp, datetime)
