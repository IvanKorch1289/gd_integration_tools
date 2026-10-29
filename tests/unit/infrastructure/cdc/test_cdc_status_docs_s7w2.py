"""Regression-тест для CDC status-claims из ARCHITECTURE.md (Sprint 7 Docs 2).

Пинит фактический статус каждого backend'а, чтобы future drift
между docstring/architecture.md и реальной реализацией ловился CI.

Покрывает (per ARCHITECTURE.md:160-169):

* ``PollCDCBackend`` → **implemented** при наличии ``sql_executor``
  (составной курсор ``(timestamp, PK)``, ADR-0384); без executor'а —
  честно «not implemented» (health-status), а не scaffold-заглушка.
* ``ListenNotifyCDCBackend`` → **implemented** (``asyncpg.add_listener``,
  ADR-0384).
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


# --- 2. PollCDCBackend: honest status ---------------------------------------


def test_poll_backend_class_docstring_declares_not_implemented_mode() -> None:
    """ADR-0384: polling-режим без ``sql_executor`` честно объявлен как
    «не реализован» (вместо молчаливого scaffold-цикла)."""
    doc = PollCDCBackend.__doc__ or ""
    assert "не реализован" in doc.lower() or "not implemented" in doc.lower(), (
        f"PollCDCBackend class docstring lost 'not implemented' marker: {doc!r}"
    )


@pytest.mark.asyncio
async def test_poll_backend_polling_mode_without_executor_yields_no_events() -> None:
    """Polling-mode без ``sql_executor`` — честно выключен (0 событий)."""
    backend = PollCDCBackend(profile="test", interval_s=0.01)
    events: list[object] = []

    async def consume_with_timeout() -> None:
        async for evt in backend.subscribe(tables=["t"]):
            events.append(evt)
            if len(events) > 0:  # safety: режим без executor'а — no-op
                break

    task = asyncio.create_task(consume_with_timeout())
    await asyncio.sleep(0.05)  # polling-loop крутится
    await backend.close()
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except TimeoutError:
        task.cancel()
    assert events == [], (
        f"PollCDCBackend polling-mode yielded events; not-implemented-контракт "
        f"нарушен: {events!r}"
    )

    health = await backend.health_check()
    assert health["status"] == "not_implemented"


# --- 3. ListenNotifyCDCBackend: implemented ---------------------------------


def test_listen_notify_backend_uses_asyncpg_listener() -> None:
    """ADR-0384: backend реализован через ``asyncpg.add_listener``."""
    source = _LISTEN_PATH.read_text(encoding="utf-8")
    assert "add_listener" in source, "ListenNotify backend lost asyncpg listener"
    assert "asyncpg.connect" in source, "ListenNotify backend lost asyncpg.connect"


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
