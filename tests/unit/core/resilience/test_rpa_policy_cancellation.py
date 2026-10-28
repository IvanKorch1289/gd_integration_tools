"""ADR-0368 — ``RPACallPolicy`` не должна глотать ``asyncio.CancelledError``.

До фикса ``except BaseException`` превращал отмену задачи в
``RPACallExhausted`` + запись в DLQ (ложный DLQ) — отмена задачи не
проходила наверх.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.core.resilience.rpa_policy import RPACallPolicy


@pytest.mark.unit
class TestRPAPolicyCancellation:
    """Отмена задачи — не «отказ вызова»."""

    async def test_cancelled_error_propagates(self) -> None:
        writer = AsyncMock()
        policy = RPACallPolicy("test", max_attempts=3, dlq_writer=writer)

        async def _factory() -> str:
            raise asyncio.CancelledError

        with patch(
            "src.backend.core.resilience.rpa_policy.feature_flags"
        ) as mock_flags:
            mock_flags.rpa_resilience_wrapper_enabled = True
            with pytest.raises(asyncio.CancelledError):
                await policy.call(_factory, transport="desktop_rpa")

        writer.write.assert_not_called()
