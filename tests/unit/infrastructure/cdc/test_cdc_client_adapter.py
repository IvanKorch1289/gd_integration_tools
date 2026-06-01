"""Тесты CDCClientAdapter (Wave 5)."""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from src.backend.infrastructure.cdc.cdc_client_adapter import (
    CDCClientAdapter,
    _client_event_to_source,
)


def test_client_event_to_source() -> None:
    """_client_event_to_source корректно мапит поля."""
    raw = {
        "operation": "INSERT",
        "table": "orders",
        "timestamp": "2026-06-01T12:00:00+00:00",
        "profile": "pg_prod",
        "new": {"id": 1},
        "old": None,
    }
    event = _client_event_to_source(raw)
    assert event.operation == "INSERT"
    assert event.table == "orders"
    assert event.new == {"id": 1}


@pytest.mark.asyncio
async def test_adapter_subscribe_yields_events() -> None:
    """Adapter yield'ит события, полученные через CDCClient callback."""
    client = AsyncMock()
    client.subscribe = AsyncMock(return_value="sub-123")
    client.unsubscribe = AsyncMock(return_value=True)

    adapter = CDCClientAdapter(profile="pg", client=client)

    captured_callback = None

    async def _subscribe(*, callback: object, **kwargs: object) -> str:
        nonlocal captured_callback
        captured_callback = callback
        return "sub-123"

    client.subscribe.side_effect = _subscribe

    async def _producer() -> None:
        await asyncio.sleep(0.01)
        if captured_callback:
            await captured_callback(
                {
                    "operation": "UPDATE",
                    "table": "users",
                    "timestamp": "2026-06-01T12:00:00+00:00",
                    "profile": "pg",
                    "new": {"name": "Alice"},
                    "old": {"name": "Bob"},
                }
            )

    producer_task = asyncio.create_task(_producer())
    events = []
    async for event in adapter.subscribe(tables=["users"]):
        events.append(event)
        await adapter.close()
        break

    await producer_task
    assert len(events) == 1
    assert events[0].operation == "UPDATE"
    assert events[0].table == "users"
    client.unsubscribe.assert_awaited_once_with("sub-123")
