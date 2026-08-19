"""Sprint 12 P1-4: PollCDCBackend real SQL via sql_executor.

Tests use `asyncio.wait_for` for timeout (Python 3.11+ compatible).
Each test creates a backend, runs subscribe() in a coroutine, and
stops the backend via `_stopped.set()` to break the polling loop.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.backend.infrastructure.cdc.poll_backend import PollCDCBackend


async def _collect_events(backend: PollCDCBackend, tables: list[str], max_events: int) -> list:
    """Collect up to max_events from backend, then stop."""
    events = []
    try:
        async for ev in backend.subscribe(tables=tables):
            events.append(ev)
            if len(events) >= max_events:
                backend._stopped.set()
                break
            if ev.new and ev.new.get("id", 0) >= max_events:
                backend._stopped.set()
                break
    except asyncio.CancelledError:
        pass
    finally:
        backend._stopped.set()  # always stop
    return events


@pytest.mark.asyncio
async def test_poll_backend_with_sql_executor_yields_events() -> None:
    """Sprint 12 P1-4: executor returns rows → backend yields CDCEvent per row."""
    rows = [
        {"id": 1, "name": "Alice", "updated_at": "2026-08-19T10:00:00Z"},
        {"id": 2, "name": "Bob", "updated_at": "2026-08-19T10:01:00Z"},
    ]

    call_count = 0

    async def fake_executor(sql: str, params: list[Any]) -> list[dict[str, Any]]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return rows
        return []

    backend = PollCDCBackend(
        profile="test_profile",
        interval_s=0,
        table="users",
        sql_executor=fake_executor,
    )

    events = await asyncio.wait_for(
        _collect_events(backend, tables=["users"], max_events=2),
        timeout=2.0,
    )

    assert len(events) == 2
    assert events[0].operation == "UPSERT"
    assert events[0].table == "users"
    assert events[0].new == rows[0]
    assert events[1].new == rows[1]


@pytest.mark.asyncio
async def test_poll_backend_advances_cursor() -> None:
    """Sprint 12 P1-4: cursor advances to last row's timestamp."""
    rows = [
        {"id": 1, "updated_at": "2026-08-19T10:00:00Z"},
        {"id": 2, "updated_at": "2026-08-19T10:01:00Z"},
    ]

    call_count = 0

    async def fake_executor(sql: str, params: list[Any]) -> list[dict[str, Any]]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return rows
        return []

    backend = PollCDCBackend(
        profile="test",
        interval_s=0,
        table="t",
        sql_executor=fake_executor,
    )

    events = await asyncio.wait_for(
        _collect_events(backend, tables=["t"], max_events=2),
        timeout=2.0,
    )

    # Find event with id=2 и check its cursor
    last_event = events[-1] if events else None
    assert last_event is not None
    assert last_event.cursor.value == "2026-08-19T10:01:00Z"


@pytest.mark.asyncio
async def test_poll_backend_executor_error_returns_empty() -> None:
    """Sprint 12 P1-4: executor exception → handled gracefully, no events yielded."""
    call_count = 0

    async def failing_executor(sql: str, params: list[Any]) -> list[dict[str, Any]]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("DB connection lost")
        # Second call succeeds
        return [{"id": 99, "updated_at": "2026-08-19T10:02:00Z"}]

    backend = PollCDCBackend(
        profile="test",
        interval_s=0,
        table="t",
        sql_executor=failing_executor,
    )

    events = await asyncio.wait_for(
        _collect_events(backend, tables=["t"], max_events=1),
        timeout=2.0,
    )

    # First call failed (handled gracefully), second returned 1 row
    assert call_count >= 2, f"Expected >= 2 calls, got {call_count}"
    assert len(events) >= 1
    assert events[0].new["id"] == 99
