"""Tests for ``src.backend.core.async_utils.deadline_budget``.

Coverage:
    - ``from_timeout`` constructor: positive/zero/negative/NaN inputs.
    - ``remaining()`` / ``is_expired()``: monotonic clock semantics.
    - ``share()`` / ``split()``: sub-budget algebra for parallel branches.
    - ``asyncio_timeout()`` async CM: integration with ``asyncio.timeout``
      and ``DeadlineExpiredError`` re-raise semantics.
    - Immutability: frozen dataclass + slots prevent accidental mutation.
"""

from __future__ import annotations

import asyncio
import math
import time

import pytest

from src.backend.core.async_utils.deadline_budget import (
    DeadlineBudget,
    DeadlineExpiredError,
    DeadlineOverflowError,
)


class TestFromTimeout:
    """Constructor input validation."""

    def test_positive_timeout(self) -> None:
        b = DeadlineBudget.from_timeout(timeout=10.0)
        assert b.original_timeout == 10.0
        assert b.deadline_ts > time.monotonic()
        assert not b.is_expired()
        assert 9.5 <= b.remaining() <= 10.0

    def test_zero_timeout_rejected(self) -> None:
        with pytest.raises(DeadlineOverflowError, match="must be positive"):
            DeadlineBudget.from_timeout(timeout=0)

    def test_negative_timeout_rejected(self) -> None:
        with pytest.raises(DeadlineOverflowError, match="must be positive"):
            DeadlineBudget.from_timeout(timeout=-1.0)

    def test_nan_timeout_rejected(self) -> None:
        with pytest.raises(DeadlineOverflowError, match="must be positive"):
            DeadlineBudget.from_timeout(timeout=math.nan)

    def test_infinite_timeout_rejected(self) -> None:
        """``math.inf`` не должен приниматься: parent budget с inf ломает split()."""
        with pytest.raises(DeadlineOverflowError, match="must be positive"):
            DeadlineBudget.from_timeout(timeout=math.inf)

    def test_with_explicit_now(self) -> None:
        """Тестовая инъекция ``now`` для детерминированных unit-тестов."""
        b = DeadlineBudget.from_timeout(timeout=5.0, now=1000.0)
        assert b.deadline_ts == 1005.0
        assert b.remaining(now=1003.0) == pytest.approx(2.0, abs=0.01)


class TestRemainingExpired:
    """Monotonic clock semantics."""

    def test_remaining_decreases_with_time(self) -> None:
        b = DeadlineBudget.from_timeout(timeout=1.0)
        r1 = b.remaining()
        time.sleep(0.05)
        r2 = b.remaining()
        assert r2 < r1
        assert r1 - r2 == pytest.approx(0.05, abs=0.02)

    def test_remaining_floors_at_zero(self) -> None:
        b = DeadlineBudget.from_timeout(timeout=0.001)
        time.sleep(0.01)
        assert b.remaining() == 0.0
        assert b.is_expired()

    def test_is_expired_initial_state(self) -> None:
        """Свежий budget с большим timeout — НЕ expired."""
        b = DeadlineBudget.from_timeout(timeout=60.0)
        assert not b.is_expired()


class TestShare:
    """Sub-budget algebra for parallel branches."""

    def test_share_full_fraction(self) -> None:
        b = DeadlineBudget.from_timeout(timeout=10.0)
        sub = b.share(1.0)
        # Sub-budget равен parent (или меньше на 1 микросекунду).
        assert abs(sub.remaining() - b.remaining()) < 0.01

    def test_share_half(self) -> None:
        b = DeadlineBudget.from_timeout(timeout=10.0)
        sub = b.share(0.5)
        # 50% от 10s = 5s.
        assert sub.original_timeout == pytest.approx(5.0, abs=0.01)
        assert sub.remaining() < b.remaining()

    def test_share_zero_returns_expired(self) -> None:
        b = DeadlineBudget.from_timeout(timeout=10.0)
        sub = b.share(0.0)
        assert sub.is_expired()
        assert sub.original_timeout == 0.0

    def test_share_negative_rejected(self) -> None:
        b = DeadlineBudget.from_timeout(timeout=10.0)
        with pytest.raises(DeadlineOverflowError, match="\\[0.0, 1.0\\]"):
            b.share(-0.1)

    def test_share_greater_than_one_rejected(self) -> None:
        b = DeadlineBudget.from_timeout(timeout=10.0)
        with pytest.raises(DeadlineOverflowError, match="\\[0.0, 1.0\\]"):
            b.share(1.5)

    def test_split_alias(self) -> None:
        """``split`` — alias для ``share``, должен быть идентичен."""
        b = DeadlineBudget.from_timeout(timeout=10.0)
        a = b.share(0.3)
        c = b.split(0.3)
        assert a.original_timeout == pytest.approx(c.original_timeout, abs=0.01)

    def test_parent_unchanged_after_share(self) -> None:
        """``share`` создаёт sub-budget; parent не мутирует."""
        b = DeadlineBudget.from_timeout(timeout=10.0)
        original_remaining = b.remaining()
        _ = b.share(0.5)
        assert abs(b.remaining() - original_remaining) < 0.01


class TestImmutability:
    """Frozen + slots предотвращают accidental mutation."""

    def test_frozen(self) -> None:
        b = DeadlineBudget.from_timeout(timeout=5.0)
        with pytest.raises((AttributeError, Exception)):  # FrozenInstanceError subclass
            b.original_timeout = 100.0  # type: ignore[misc]

    def test_slots_no_dict(self) -> None:
        b = DeadlineBudget.from_timeout(timeout=5.0)
        assert not hasattr(b, "__dict__"), "slots=True → no __dict__ overhead"


class TestAsyncTimeoutContextManager:
    """Интеграция с ``asyncio.timeout``."""

    @pytest.mark.asyncio
    async def test_pass_through(self) -> None:
        b = DeadlineBudget.from_timeout(timeout=5.0)
        async with b.asyncio_timeout():
            await asyncio.sleep(0.01)
        # Без exception — успешный проход.

    @pytest.mark.asyncio
    async def test_exceeded_raises_deadline_expired(self) -> None:
        b = DeadlineBudget.from_timeout(timeout=0.1)
        with pytest.raises(DeadlineExpiredError) as exc_info:
            async with b.asyncio_timeout():
                await asyncio.sleep(1.0)
        assert exc_info.value.original_timeout == pytest.approx(0.1, abs=0.001)

    @pytest.mark.asyncio
    async def test_expired_at_entry_raises_immediately(self) -> None:
        b = DeadlineBudget.from_timeout(timeout=0.001)
        await asyncio.sleep(0.01)
        with pytest.raises(DeadlineExpiredError, match="already expired"):
            async with b.asyncio_timeout():
                pytest.fail("body should not run")

    @pytest.mark.asyncio
    async def test_nested_sub_budgets(self) -> None:
        """Parent budget и sub-budget работают независимо (parent не расходуется sub'ом)."""
        parent = DeadlineBudget.from_timeout(timeout=2.0)
        sub = parent.share(0.5)
        async with sub.asyncio_timeout():
            await asyncio.sleep(0.01)
        # После выхода sub-budget должен быть близок к истечению,
        # но parent не должен быть сильно уменьшен (sub-budget
        # использует независимый deadline_ts).
        assert parent.remaining() > 1.0


class TestErrorInheritance:
    """Backward-compat: оба error-класса должны перехватываться как ``asyncio.TimeoutError``."""

    def test_deadline_expired_is_asyncio_timeout(self) -> None:
        e = DeadlineExpiredError("test", original_timeout=1.0)
        assert isinstance(e, asyncio.TimeoutError)
        # ``except TimeoutError`` должен ловить.
        try:
            raise e
        except TimeoutError as caught:
            assert caught is e


class TestUsagePatterns:
    """Документирующие тесты для типовых сценариев использования."""

    @pytest.mark.asyncio
    async def test_parallel_branches_split_budget(self) -> None:
        """Каждая ветвь получает долю parent budget; parent не расходуется."""
        parent = DeadlineBudget.from_timeout(timeout=10.0)
        a = parent.share(0.5)
        b = parent.share(0.5)
        # Параллельные ветви.
        await asyncio.gather(
            asyncio.sleep(0.01),  # branch a work
            asyncio.sleep(0.01),  # branch b work
        )
        # Обе ветви должны иметь ~5s бюджета, parent ~10s.
        assert a.remaining() > 4.0
        assert b.remaining() > 4.0

    @pytest.mark.asyncio
    async def test_saga_compensation_pattern(self) -> None:
        """Saga forward-фаза тратит budget; compensation получает остаток."""
        main_budget = DeadlineBudget.from_timeout(timeout=2.0)
        # Forward step тратит 0.5s.
        await asyncio.sleep(0.5)
        assert main_budget.remaining() < 1.6
        # Compensation получает часть оставшегося.
        comp_budget = main_budget.share(0.3)
        # ~30% от ~1.5s = ~0.45s.
        assert comp_budget.remaining() < 1.0
