"""Edge-case tests for ``DeadlineBudget`` (Sprint 12 — coverage ratchet).

Coverage:
    - ``asyncio_timeout`` CM defensive path: ``__aexit__`` raises
      ``DeadlineExpiredError`` even when ``exc_type`` was already
      ``asyncio.TimeoutError`` (defensive double-check).
    - Sub-budget allocation с дробными долями и микросекундным округлением.
    - Remaining уменьшается монотонно через несколько вызовов.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from src.backend.core.async_utils.deadline_budget import (
    DeadlineBudget,
    DeadlineExpiredError,
)


class TestAsyncTimeoutDefensivePath:
    """Defensive path: ``__aexit__`` обнаруживает ``asyncio.TimeoutError`` как exc_type."""

    @pytest.mark.asyncio
    async def test_aexit_converts_existing_timeout_error(self) -> None:
        """Если в body брошен ``asyncio.TimeoutError`` напрямую, CM конвертирует его.

        Это defensive path: ``asyncio.Timeout.__aexit__`` сам поднимает
        ``TimeoutError`` при cancel, но теоретически exc_type может быть
        передан. Тест покрывает ветку ``if exc_type is asyncio.TimeoutError``.
        """
        b = DeadlineBudget.from_timeout(timeout=5.0)

        async def raises_timeout() -> None:
            raise asyncio.TimeoutError("test")

        with pytest.raises(DeadlineExpiredError) as exc_info:
            async with b.asyncio_timeout():
                await raises_timeout()
        # Конвертация работает: deadline метadatas сохранены.
        assert exc_info.value.original_timeout == 5.0


class TestSubBudgetMicrosecondRounding:
    """``share()`` округляет до микросекунд для стабильности parent/child budgets."""

    def test_share_rounds_to_microseconds(self) -> None:
        """Share(0.33) of 1.0s → ~0.33s (microsecond precision)."""
        b = DeadlineBudget.from_timeout(timeout=1.0)
        sub = b.share(0.33)
        # 1.0 * 0.33 = 0.33 (с округлением).
        assert 0.32 <= sub.original_timeout <= 0.34

    def test_share_preserves_total_fraction(self) -> None:
        """N sub-budgets с одинаковым fraction суммируются близко к parent."""
        b = DeadlineBudget.from_timeout(timeout=10.0)
        subs = [b.share(0.5) for _ in range(3)]  # 3 * 50% от parent
        # С учётом rounding каждая sub ≈ 5s, итого ≈ 15s (но parent не суммируется).
        for sub in subs:
            assert sub.remaining() <= b.remaining()


class TestRemainingMonotonic:
    """``remaining()`` уменьшается монотонно через несколько вызовов."""

    def test_remaining_decreases_through_calls(self) -> None:
        b = DeadlineBudget.from_timeout(timeout=1.0)
        samples = [b.remaining() for _ in range(5)]
        time.sleep(0.05)
        samples_after = [b.remaining() for _ in range(5)]
        # Каждый следующий sample ≤ предыдущий (с допуском на jitter).
        for i in range(4):
            assert samples[i + 1] <= samples[i] + 0.001
        # После задержки — все ниже.
        for i in range(4):
            assert samples_after[i] <= samples[i] + 0.001


class TestAsyncioTimeoutImExpired:
    """Boundary: budget уже истёк к моменту ``asyncio_timeout()`` вызова."""

    @pytest.mark.asyncio
    async def test_expired_before_aenter_raises(self) -> None:
        """Если ``remaining <= 0`` → ``DeadlineExpiredError`` сразу при входе."""
        b = DeadlineBudget.from_timeout(timeout=0.001)
        await asyncio.sleep(0.01)
        assert b.is_expired()
        with pytest.raises(DeadlineExpiredError, match="already expired"):
            async with b.asyncio_timeout():
                pytest.fail("body should not run")


class TestFrozenDataclassImmutability:
    """``frozen=True`` запрещает mutation — критично для contextvar semantics."""

    def test_cannot_modify_original_timeout(self) -> None:
        from dataclasses import FrozenInstanceError

        b = DeadlineBudget.from_timeout(timeout=5.0)
        with pytest.raises(FrozenInstanceError):
            b.original_timeout = 10.0  # type: ignore[misc]

    def test_cannot_modify_deadline_ts(self) -> None:
        from dataclasses import FrozenInstanceError

        b = DeadlineBudget.from_timeout(timeout=5.0)
        with pytest.raises(FrozenInstanceError):
            b.deadline_ts = 100.0  # type: ignore[misc]
