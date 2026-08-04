"""Regression-тест для CDC status-claims из ARCHITECTURE.md (Sprint 7 Docs 2).

Пинит фактический статус каждого backend'а, чтобы future drift
между docstring/architecture.md и реальной реализацией ловился CI.

Покрывает (per ARCHITECTURE.md:160-169):

* ``PollCDCBackend`` → **scaffold** (polling-mode без ``feed`` —
  heartbeat-cursor advance без реальных SELECT'ов; Wave R3).
* ``ListenNotifyCDCBackend`` → **scaffold** (``subscribe()`` ждёт
  ``_stopped.wait()`` без реального ``asyncpg.add_listener``; Wave R3).
* ``DebeziumEventsCDCBackend`` → **implemented** (322 LOC через
  ``aiokafka.AIOKafkaConsumer``: subscribe/ack/replay/close —
  см. ``debezium_events_backend.py:104``).

Reference: ``src/backend/infrastructure/cdc/``.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from src.backend.infrastructure.cdc.debezium_events_backend import (
    DebeziumEventsCDCBackend,
)
from src.backend.infrastructure.cdc.listen_notify_backend import ListenNotifyCDCBackend
from src.backend.infrastructure.cdc.poll_backend import PollCDCBackend

# ruff: noqa: S101 — pytest asserts required


# --- Paths ------------------------------------------------------------------


_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEBEZIUM_PATH = (
    _REPO_ROOT / "src/backend/infrastructure/cdc/debezium_events_backend.py"
)
_POLL_PATH = _REPO_ROOT / "src/backend/infrastructure/cdc/poll_backend.py"
_LISTEN_PATH = _REPO_ROOT / "src/backend/infrastructure/cdc/listen_notify_backend.py"
_ARCHITECTURE_MD = _REPO_ROOT / "ARCHITECTURE.md"


# --- 1. Debezium: implemented ----------------------------------------------


def test_debezium_is_subclass_of_cdc_source() -> None:
    """``DebeziumEventsCDCBackend`` имплементирует ``CDCSource`` Protocol.

    Pre-existing contract; см. ``debezium_events_backend.py:104``.
    """
    from src.backend.core.cdc.source import CDCSource

    assert issubclass(DebeziumEventsCDCBackend, CDCSource)


def test_debezium_class_docstring_marks_implemented() -> None:
    """Class docstring ``DebeziumEventsCDCBackend`` явно говорит production-ready.

    ARCHITECTURE.md:169 ссылается на эту docstring через file:line ref.
    """
    doc = DebeziumEventsCDCBackend.__doc__ or ""
    assert "production-ready" in doc.lower(), (
        f"Debezium class docstring lost 'production-ready' marker: {doc!r}"
    )


def test_debezium_exposes_full_lifecycle_methods() -> None:
    """Debezium backend реализует полный subscribe/ack/replay/close loop."""
    import inspect

    for method_name in ("subscribe", "ack", "replay", "close"):
        method = getattr(DebeziumEventsCDCBackend, method_name, None)
        assert method is not None, f"DebeziumEventsCDCBackend.{method_name} missing"
        # subscribe/replay — async generators (yield); ack/close — coroutines.
        is_async = inspect.iscoroutinefunction(method) or inspect.isasyncgenfunction(
            method
        )
        assert is_async, (
            f"DebeziumEventsCDCBackend.{method_name} must be async "
            f"(coroutine or async generator)"
        )


def test_debezium_source_uses_aiokafka() -> None:
    """Debezium implementation зависит от ``aiokafka`` (НЕ faststream)."""
    source = _DEBEZIUM_PATH.read_text(encoding="utf-8")
    assert "aiokafka" in source, "Debezium backend lost aiokafka dependency"
    assert "AIOKafkaConsumer" in source, "Debezium backend lost AIOKafkaConsumer usage"


def test_debezium_implements_parse_helper() -> None:
    """``parse_debezium_event`` экспортируется и возвращает CDCEvent/None."""
    from src.backend.core.cdc.source import CDCEvent
    from src.backend.infrastructure.cdc.debezium_events_backend import (
        parse_debezium_event,
    )

    # INSERT event
    event = parse_debezium_event(
        {"op": "c", "source": {"table": "t", "db": "db"}, "after": {"x": 1}},
        kafka_offset=0,
        kafka_partition=0,
    )
    assert isinstance(event, CDCEvent)
    assert event.operation == "INSERT"

    # Unknown op → None (не-Дебезькиум payload)
    assert (
        parse_debezium_event(
            {"op": "x", "source": {"table": "t"}}, kafka_offset=0, kafka_partition=0
        )
        is None
    )


# --- 2. PollCDCBackend: scaffold -------------------------------------------


def test_poll_backend_class_docstring_marks_scaffold() -> None:
    """Class docstring ``PollCDCBackend`` явно говорит scaffold."""
    doc = PollCDCBackend.__doc__ or ""
    assert "scaffold" in doc.lower(), (
        f"PollCDCBackend class docstring lost 'scaffold' marker: {doc!r}"
    )


@pytest.mark.asyncio
async def test_poll_backend_polling_mode_is_scaffold_no_events() -> None:
    """Polling-mode (без ``feed``) — heartbeat-cursor advance без yield'а событий.

    Pre-existing scaffold behaviour; Wave R3 принесёт реальные SELECT'ы.
    """
    backend = PollCDCBackend(profile="test", interval_s=0.01)
    events: list[object] = []

    async def consume_with_timeout() -> None:
        async for evt in backend.subscribe(tables=["t"]):
            events.append(evt)
            if len(events) > 0:  # safety: scaffold должен быть no-op
                break

    task = asyncio.create_task(consume_with_timeout())
    await asyncio.sleep(0.05)  # polling-loop крутится
    await backend.close()
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except asyncio.TimeoutError:
        task.cancel()
    assert events == [], (
        f"PollCDCBackend polling-mode yielded events; scaffold-контракт нарушен: {events!r}"
    )


# --- 3. ListenNotifyCDCBackend: scaffold -----------------------------------


def test_listen_notify_class_docstring_marks_scaffold() -> None:
    """Class docstring ``ListenNotifyCDCBackend`` явно говорит scaffold."""
    doc = ListenNotifyCDCBackend.__doc__ or ""
    assert "scaffold" in doc.lower(), (
        f"ListenNotifyCDCBackend class docstring lost 'scaffold' marker: {doc!r}"
    )


@pytest.mark.asyncio
async def test_listen_notify_subscribe_blocks_until_close() -> None:
    """``subscribe()`` ждёт ``_stopped.wait()`` без реального ``asyncpg.add_listener``.

    Pre-existing scaffold behaviour; Wave R3 принесёт реальный listener.
    """
    backend = ListenNotifyCDCBackend(dsn="postgresql://test:test@localhost/test")
    events: list[object] = []

    async def consume_with_timeout() -> None:
        async for evt in backend.subscribe(tables=["t"]):
            events.append(evt)
            break  # safety; scaffold должен быть no-op

    task = asyncio.create_task(consume_with_timeout())
    await asyncio.sleep(0.05)  # subscribe должен висеть в wait
    await backend.close()  # это выводит subscribe из wait
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except asyncio.TimeoutError:
        task.cancel()
    assert events == [], (
        f"ListenNotifyCDCBackend.subscribe yielded events; scaffold-контракт нарушен: {events!r}"
    )


def test_listen_notify_replay_is_unsupported_scaffold() -> None:
    """``replay()`` явно логирует unsupported (live-stream only)."""
    import inspect

    source = inspect.getsource(ListenNotifyCDCBackend.replay)
    assert "not supported" in source.lower(), (
        f"ListenNotifyCDCBackend.replay lost 'not supported' scaffold marker: {source!r}"
    )


# --- 4. ARCHITECTURE.md: table consistency ---------------------------------


@pytest.fixture(scope="module")
def architecture_cdc_section() -> str:
    """ARCHITECTURE.md:160-169 — CDC Status section."""
    text = _ARCHITECTURE_MD.read_text(encoding="utf-8")
    match = re.search(
        r"#### CDC Status \(Sprint 18 W0\)(.*?)(?=\n#### |\n### )",
        text,
        flags=re.DOTALL,
    )
    assert match is not None, "CDC Status section not found in ARCHITECTURE.md"
    return match.group(1)


def test_architecture_marks_debezium_as_implemented(
    architecture_cdc_section: str,
) -> None:
    """ARCHITECTURE.md CDC table: Debezium row → ``**implemented**``."""
    assert "**implemented**" in architecture_cdc_section
    assert "debezium_events_backend.py:104" in architecture_cdc_section, (
        "Debezium row lost file:line ref to debezium_events_backend.py:104"
    )


def test_architecture_marks_poll_as_scaffold(architecture_cdc_section: str) -> None:
    """ARCHITECTURE.md CDC table: Polling row → ``**scaffold**`` (pre-existing)."""
    # Найдём строку с ``poll_backend.py`` и проверим scaffold-маркер.
    poll_line = next(
        (ln for ln in architecture_cdc_section.splitlines() if "poll_backend.py" in ln),
        None,
    )
    assert poll_line is not None, "Polling row missing in ARCHITECTURE.md CDC table"
    assert "**scaffold**" in poll_line, (
        f"Polling row should be marked scaffold (pre-existing): {poll_line!r}"
    )


def test_architecture_marks_listen_notify_as_scaffold(
    architecture_cdc_section: str,
) -> None:
    """ARCHITECTURE.md CDC table: Listen/Notify row → ``**scaffold**``."""
    ln_line = next(
        (
            ln
            for ln in architecture_cdc_section.splitlines()
            if "listen_notify_backend.py" in ln
        ),
        None,
    )
    assert ln_line is not None, "Listen/Notify row missing in ARCHITECTURE.md CDC table"
    assert "**scaffold**" in ln_line, (
        f"Listen/Notify row should be marked scaffold: {ln_line!r}"
    )


def test_architecture_no_stale_production_ready_for_poll_or_listen(
    architecture_cdc_section: str,
) -> None:
    """ARCHITECTURE.md CDC table: НЕТ ``production-ready`` для Poll или Listen/Notify.

    Регрессия: Sprint 18 W0 помечал оба как production-ready, что не
    соответствует реальному коду.
    """
    for fname in ("poll_backend.py", "listen_notify_backend.py"):
        row = next(
            (ln for ln in architecture_cdc_section.splitlines() if fname in ln), None
        )
        assert row is not None, f"{fname} row missing"
        assert "production-ready" not in row, (
            f"{fname} row still marked production-ready (stale doc): {row!r}"
        )
