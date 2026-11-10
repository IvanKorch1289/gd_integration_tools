"""Circuit breaker + bulkhead для внешних вызовов DSL-процессоров (ADR-0436).

Контекст
--------
Фасады устойчивости (:mod:`src.backend.core.api.resilience`) существовали, но
DSL-процессоры внешних вызовов (``http_call``, ``soap_call``, ``grpc_call``,
``ws_publish``, ``mq_publish``) их **не использовали**: при отказе внешнего
сервиса каждый worker блокировался на полный таймаут шага, пул конкурентных
вызовов не ограничивался, а отказ одного сервиса каскадировал на остальные.

Решение
-------
Единая обёртка :func:`guarded_external_call`:

* **Circuit breaker** — именованный (``dsl:<processor>``) в общем реестре
  (:func:`src.backend.core.resilience.breaker.get_breaker_registry`); пороги
  берутся из настроек HTTP (``circuit_breaker_max_failures`` /
  ``circuit_breaker_reset_timeout``). При открытом breaker'е вызов падает
  быстро (``CircuitOpen``), а не ждёт таймаут.
* **Bulkhead** — ограничение конкурентных вызовов к одному ресурсу
  (``Bulkhead.guard``): при исчерпании слотов — ``BulkheadExhausted`` вместо
  неограниченного накопления вызовов.

Параметры bulkhead'а можно переопределить настройками профиля
(``DSL_BULKHEAD_MAX_CONCURRENT`` / ``DSL_BULKHEAD_WAIT_TIMEOUT``).
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import TypeVar

__all__ = ("guarded_external_call",)

T = TypeVar("T")

#: Значения по умолчанию для bulkhead'а внешних вызовов DSL.
_DEFAULT_MAX_CONCURRENT = 16
_DEFAULT_WAIT_TIMEOUT = 5.0


def _bulkhead_limit() -> int:
    """Максимум одновременных внешних вызовов (настройка/окружение)."""
    raw = os.getenv("DSL_BULKHEAD_MAX_CONCURRENT", "")
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return _DEFAULT_MAX_CONCURRENT


def _bulkhead_wait_timeout() -> float:
    """Таймаут ожидания свободного слота bulkhead'а (настройка/окружение)."""
    raw = os.getenv("DSL_BULKHEAD_WAIT_TIMEOUT", "")
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_WAIT_TIMEOUT
    return value if value > 0 else _DEFAULT_WAIT_TIMEOUT


def _get_breaker(name: str):  # type: ignore[no-untyped-def]
    """Именованный circuit breaker для DSL-процессора.

    Args:
        name: Имя процессора (``http_call`` и т.п.).

    Returns:
        Breaker из общего реестра (создаётся при первом обращении).

    """
    from src.backend.core.config.http_base import http_base_settings
    from src.backend.core.resilience.breaker import BreakerSpec, get_breaker_registry

    breaker_name = f"dsl:{name}"
    return get_breaker_registry().get_or_create(
        breaker_name,
        BreakerSpec(
            name=breaker_name,
            failure_threshold=http_base_settings.circuit_breaker_max_failures,
            recovery_timeout=float(http_base_settings.circuit_breaker_reset_timeout),
        ),
    )


def _get_bulkhead(name: str):  # type: ignore[no-untyped-def]
    """Именованный bulkhead для DSL-процессора.

    Args:
        name: Имя процессора.

    Returns:
        Bulkhead из общего реестра (создаётся при первом обращении).

    """
    from src.backend.core.resilience.bulkhead_registry import get_bulkhead_registry
    from src.backend.infrastructure.resilience.bulkhead import Bulkhead

    registry = get_bulkhead_registry()
    bulkhead = registry.get(f"dsl:{name}")
    if bulkhead is None:
        bulkhead = Bulkhead(
            name=f"dsl:{name}",
            max_concurrent=_bulkhead_limit(),
            wait_timeout=_bulkhead_wait_timeout(),
        )
        registry.register(f"dsl:{name}", bulkhead)
    return bulkhead


async def guarded_external_call(name: str, call: Callable[[], Awaitable[T]]) -> T:
    """Выполнить внешний вызов под circuit breaker'ом и bulkhead'ом.

    Args:
        name: Имя процессора/ресурса (используется как имя breaker'а и
            bulkhead'а: ``dsl:<name>``).
        call: Корутина внешнего вызова.

    Returns:
        Результат вызова.

    Raises:
        CircuitOpen: Breaker открыт — вызов отклонён без обращения к сервису.
        BulkheadExhausted: Все слоты bulkhead'а заняты.

    """
    breaker = _get_breaker(name)
    bulkhead = _get_bulkhead(name)
    async with breaker.guard():
        async with bulkhead.guard():
            return await call()
