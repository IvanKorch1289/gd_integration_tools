"""Unit-тесты для CDC source cycle-22 fix: P0-2 PG LSN ack.

Проверяет что _emit() теперь re-raises on_event failure, поэтому
send_feedback НЕ выполняется после ошибки → PG redelivers event.
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.infrastructure.sources.cdc import CDCSource


@pytest.mark.asyncio
async def test_cdc_emit_raises_on_callback_error():
    """P0-2: on_event failure must propagate, NOT be swallowed."""
    source = CDCSource.__new__(CDCSource)  # bypass __init__
    source.source_id = "test"
    source._slot = "test_slot"
    source._plugin = "pg"

    msg = MagicMock()
    msg.data_start = "0/1234"
    msg.cursor = MagicMock()
    msg.cursor.send_feedback = AsyncMock()

    async def failing_callback(event):
        raise RuntimeError("downstream failed")

    with pytest.raises(RuntimeError, match="downstream failed"):
        await source._emit(failing_callback, msg)

    # send_feedback must NOT have been called
    msg.cursor.send_feedback.assert_not_called()


@pytest.mark.asyncio
async def test_cdc_emit_success_calls_callback():
    """Sanity: happy path still emits event without raising."""
    source = CDCSource.__new__(CDCSource)
    source.source_id = "test"
    source._slot = "test_slot"
    source._plugin = "pg"

    msg = MagicMock()
    msg.data_start = "0/1234"
    msg.payload = b'{"change": "data"}'
    msg.cursor = MagicMock()

    received = []

    async def cb(event):
        received.append(event)

    await source._emit(cb, msg)
    assert len(received) == 1
    assert received[0].payload["lsn"] == "0/1234"
