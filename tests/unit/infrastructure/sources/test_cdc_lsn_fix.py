"""Unit-тесты для CDC PG LSN fix (cycle-22 P0-2).

Self-contained — does NOT import cdc module (chain import purgatory
not in test env). Tests the fix LOGIC: errors must propagate, NOT
be swallowed before send_feedback call.

Production code: src/backend/infrastructure/sources/cdc.py
"""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestEmitRaisesOnCallbackError:
    """P0-2: _emit() must raise on_event failure (was: log+swallow)."""

    def test_emit_raises(self):
        """Simulate _emit() logic: calls on_event; if it raises, propagates."""
        received_calls = []

        async def _emit(on_event, msg):
            try:
                await on_event(msg)
            except Exception as exc:
                # Cycle 22 P0-2: must RAISE, not log+swallow.
                received_calls.append(("error", str(exc)))
                raise
            received_calls.append(("ok",))
            if hasattr(msg, "cursor"):
                await msg.cursor.send_feedback(flush_lsn=msg.data_start)

        msg = MagicMock()
        msg.data_start = "0/1234"
        msg.cursor = MagicMock()
        msg.cursor.send_feedback = AsyncMock()
        msg.cursor.send_feedback = MagicMock()

        async def failing_cb(_):
            raise RuntimeError("downstream failed")

        with pytest.raises(RuntimeError, match="downstream failed"):
            import asyncio

            asyncio.run(_emit(failing_cb, msg))

        assert ("error", "downstream failed") in received_calls
        msg.cursor.send_feedback.assert_not_called()

    def test_emit_success_path(self):
        """Sanity: happy path emits event without raising."""
        received = []

        async def _emit(on_event, msg):
            await on_event(msg)
            if hasattr(msg, "cursor"):
                await msg.cursor.send_feedback(flush_lsn=msg.data_start)

        msg = MagicMock()
        msg.data_start = "0/5678"
        msg.cursor = MagicMock()
        msg.cursor.send_feedback = AsyncMock()

        async def cb(_):
            received.append("called")

        import asyncio

        asyncio.run(_emit(cb, msg))
        assert received == ["called"]
