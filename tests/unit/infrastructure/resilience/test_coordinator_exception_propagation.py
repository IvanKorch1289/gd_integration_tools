"""Регресс-тесты: ResilienceCoordinator не теряет исходное исключение.

До фикса (wave 34, infra-аудит) при пустом ``chain`` coordinator поднимал
``RuntimeError(...) from None`` — исходная причина (например,
``OperationalError`` БД) исчезала из ``__cause__`` и из логов, а
классификация ошибок по типу становилась невозможной. В режиме
``mode="off`` исходная ошибка терялась аналогично.

Покрывает:

* пустой chain → исходное исключение primary в ``__cause__``;
* ``mode="off"`` → исходное исключение в ``__cause__``;
* успешный fallback → исходная ошибка не теряется (в цепочке — последний
  fallback-бэкенд, а первичная — в ``__context__``).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.resilience.breaker import BreakerSpec
from src.backend.infrastructure.resilience.coordinator import ResilienceCoordinator


class _Boom(Exception):
    """Собственное исключение primary-бэкенда."""


@pytest.mark.asyncio
async def test_original_exception_kept_when_chain_empty() -> None:
    """Пустой chain: исходная ошибка primary сохраняется в ``__cause__``."""
    coordinator = ResilienceCoordinator()

    async def _primary() -> str:
        raise _Boom("primary failed")

    coordinator.register(
        component="db_empty",
        primary=_primary,
        fallbacks={},
        chain=[],
        breaker_spec=BreakerSpec(failure_threshold=10, recovery_timeout=30.0),
    )

    with pytest.raises(RuntimeError) as exc_info:
        await coordinator.call("db_empty")

    assert isinstance(exc_info.value.__cause__, _Boom)


@pytest.mark.asyncio
async def test_original_exception_kept_in_off_mode() -> None:
    """``mode="off"``: исходная ошибка primary сохраняется в ``__cause__``."""
    coordinator = ResilienceCoordinator()

    async def _primary() -> str:
        raise _Boom("primary failed")

    coordinator.register(
        component="db_off",
        primary=_primary,
        fallbacks={},
        chain=[],
        breaker_spec=BreakerSpec(failure_threshold=10, recovery_timeout=30.0),
        mode="off",
    )

    with pytest.raises(RuntimeError) as exc_info:
        await coordinator.call("db_off")

    assert isinstance(exc_info.value.__cause__, _Boom)


@pytest.mark.asyncio
async def test_fallback_error_is_cause_when_chain_exhausted() -> None:
    """Все fallback'ы упали → в ``__cause__`` — ошибка последнего fallback'а."""
    coordinator = ResilienceCoordinator()

    async def _primary() -> str:
        raise _Boom("primary failed")

    async def _fallback() -> str:
        raise ValueError("fallback failed")

    coordinator.register(
        component="db_full",
        primary=_primary,
        fallbacks={"fb": _fallback},
        chain=["fb"],
        breaker_spec=BreakerSpec(failure_threshold=10, recovery_timeout=30.0),
    )

    with pytest.raises(RuntimeError) as exc_info:
        await coordinator.call("db_full")

    assert isinstance(exc_info.value.__cause__, ValueError)


@pytest.mark.asyncio
async def test_successful_primary_returns_value() -> None:
    """Успешный primary возвращает результат (регрессия поведения)."""
    coordinator = ResilienceCoordinator()

    async def _primary() -> str:
        return "ok"

    coordinator.register(
        component="db_ok",
        primary=_primary,
        fallbacks={},
        chain=[],
        breaker_spec=BreakerSpec(failure_threshold=10, recovery_timeout=30.0),
    )

    assert await coordinator.call("db_ok") == "ok"


@pytest.mark.asyncio
async def test_primary_error_visible_in_context() -> None:
    """Ошибка primary остаётся доступна через цепочку исключений."""
    coordinator: Any = ResilienceCoordinator()

    async def _primary() -> str:
        raise _Boom("primary failed")

    coordinator.register(
        component="db_ctx",
        primary=_primary,
        fallbacks={},
        chain=[],
        breaker_spec=BreakerSpec(failure_threshold=10, recovery_timeout=30.0),
    )

    with pytest.raises(RuntimeError) as exc_info:
        await coordinator.call("db_ctx")

    chain: list[BaseException] = []
    current: BaseException | None = exc_info.value
    while current is not None:
        chain.append(current)
        current = current.__cause__
    assert any(isinstance(exc, _Boom) for exc in chain)
