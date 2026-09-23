"""SensorProcessor — Airflow-совместимый sensor для DSL-маршрутов.

Два режима (семантика Apache Airflow):

- **poke** (default): одна проверка условия; ``False`` → ``exchange.fail``.
  Для быстрых условий (файл появился, флаг выставлен).
- **reschedule**: поллинг условия с паузой ``interval_s``, ограниченный
  ``timeout_s``; между проверками процессор «отдаёт» event loop
  (``await asyncio.sleep``). Для долгих ожиданий без блокировки воркера.

Интеграция с deadline-budget (ADR-0305): ``timeout_s`` сужается до
``budget.remaining()``; если budget истёк на входе — ``exchange.fail``
без единой проверки (admission control). ``DeadlineExpiredError``
пробрасывается, остальные ошибки резолва контекста — graceful degradation.

Безопасный дефолт: ``reschedule`` без ``timeout_s`` и без budget выполняет
ОДНУ проверку (fallback на poke-семантику) — исключает бесконечный
цикл в pipeline.

Predicate — sync-коллбэк ``Callable[[Exchange], bool]``. Для async-условий
оберните в готовый ``asyncio.Event``/poller-обёртку.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = ("SensorProcessor",)


class SensorProcessor(BaseProcessor):
    """Ждёт выполнения условия (poke) или поллит его (reschedule)."""

    def __init__(
        self,
        predicate: Callable[[Exchange[Any]], bool],
        *,
        mode: str = "poke",
        interval_s: float = 5.0,
        timeout_s: float | None = None,
        name: str | None = None,
    ) -> None:
        """Инициализация sensor'а.

        Args:
            predicate: условие готовности; ``True`` → маршрут продолжается.
            mode: ``"poke"`` (одна проверка) или ``"reschedule"`` (поллинг).
            interval_s: пауза между проверками в reschedule-режиме (>0).
            timeout_s: общий бюджет ожидания в reschedule-режиме.
                ``None`` → одна проверка (безопасный дефолт, см. module docstring).
            name: имя процессора.

        Raises:
            ValueError: неизвестный mode или interval_s <= 0.
        """
        if mode not in ("poke", "reschedule"):
            raise ValueError(f"SensorProcessor: неизвестный mode '{mode}'")
        if interval_s <= 0:
            raise ValueError("SensorProcessor: interval_s должен быть > 0")
        super().__init__(name=name or f"sensor({mode})")
        self._predicate = predicate
        self._mode = mode
        self._interval_s = interval_s
        self._timeout_s = timeout_s

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Проверяет условие согласно mode (см. module docstring)."""
        effective_timeout = self._timeout_s
        try:
            from src.backend.core.async_utils.deadline_budget import (  # noqa: F401 — re-export
                DeadlineExpiredError,
            )
            from src.backend.core.request_context import RequestContext

            ctx = RequestContext.current()
            if ctx is not None and ctx.deadline_budget is not None:
                remaining = ctx.deadline_budget.remaining()
                if remaining <= 0.0:
                    # ADR-0305 admission control: ни одной проверки, ни одного sleep.
                    exchange.fail(
                        f"Sensor skipped: deadline budget exhausted "
                        f"({ctx.deadline_budget.original_timeout}s total)"
                    )
                    return
                if effective_timeout is not None:
                    effective_timeout = min(effective_timeout, remaining)
                else:
                    effective_timeout = remaining
        except DeadlineExpiredError:
            raise
        except Exception:
            # RequestContext недоступен — работаем без deadline (graceful).
            pass

        if self._mode == "poke":
            self._check_once(exchange)
            return

        # reschedule: без effective_timeout — безопасный дефолт (одна проверка).
        if effective_timeout is None or effective_timeout <= 0.0:
            if not self._predicate(exchange):
                exchange.fail(
                    "Sensor not ready (mode=reschedule, no timeout — single check)"
                )
            return

        deadline = time.monotonic() + effective_timeout
        while True:
            if self._check_predicate(exchange):
                return
            if time.monotonic() >= deadline:
                exchange.fail(
                    f"Sensor timeout after {effective_timeout:.3f}s "
                    f"(mode=reschedule, interval={self._interval_s}s)"
                )
                return
            await asyncio.sleep(self._interval_s)

    def _check_predicate(self, exchange: Exchange[Any]) -> bool:
        """Одна проверка условия; False → fail (poke-семантика)."""
        if self._predicate(exchange):
            return True
        if self._mode == "poke":
            exchange.fail("Sensor not ready (mode=poke, single check)")
        return False

    def _check_once(self, exchange: Exchange[Any]) -> None:
        """Единственная проверка (poke или fallback reschedule)."""
        self._check_predicate(exchange)

    def to_spec(self) -> dict[str, Any]:
        """Сериализует параметры sensor'а (predicate не сериализуется)."""
        return {
            "sensor": {
                "mode": self._mode,
                "interval_s": self._interval_s,
                "timeout_s": self._timeout_s,
            }
        }
