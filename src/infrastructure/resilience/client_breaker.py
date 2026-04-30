"""Per-client circuit breaker для infrastructure-клиентов.

Wave 6.1: backend переведён с ``aiocircuitbreaker`` на ``purgatory`` через
единый фасад ``infrastructure.resilience.breaker.BreakerRegistry``.

Класс ``ClientCircuitBreaker`` сохраняет публичный API (``guard()``,
``is_open()``, ``from_profile()``) — ``RedisClient``, FastStream-брокеры,
``HttpUpstream`` и т. п. callsite-ы продолжают работать без изменений.

State machine:
  ``closed`` → при failure_threshold подряд failures → ``open``.
  ``open`` → через ``recovery_timeout`` секунд → ``half_open``.
  ``half_open`` → первый успех закрывает; failure возвращает в ``open``.

Метрики: gauge ``infra_client_circuit_state{client,host}`` обновляется
автоматически через event-listener purgatory factory.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator, Final

from src.infrastructure.resilience.breaker import BreakerSpec, breaker_registry
from src.infrastructure.resilience.breaker import CircuitOpen as CircuitOpen

if TYPE_CHECKING:
    from src.core.config.pooling import PoolingProfile


_logger = logging.getLogger(__name__)


class ClientCircuitBreaker:
    """Адаптер фасадного ``Breaker`` для infrastructure-клиентов.

    Главное отличие от прямого использования фасада — ``host``-label для
    Prometheus-метрик и factory из ``PoolingProfile``.
    """

    def __init__(
        self,
        *,
        name: str,
        failure_threshold: int,
        recovery_timeout: float,
        host: str = "default",
    ) -> None:
        self.name = name
        self.host = host
        self._breaker = breaker_registry.get_or_create(
            f"{name}@{host}",
            BreakerSpec(
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
            ),
            host=host,
        )

    @classmethod
    def from_profile(
        cls, *, name: str, profile: "PoolingProfile", host: str = "default"
    ) -> "ClientCircuitBreaker":
        """Создать CB из ``PoolingProfile`` (circuit_threshold + circuit_recovery_s)."""
        return cls(
            name=name,
            host=host,
            failure_threshold=profile.circuit_threshold,
            recovery_timeout=profile.circuit_recovery_s,
        )

    def is_open(self) -> bool:
        return self._breaker.is_open

    @asynccontextmanager
    async def guard(self) -> AsyncIterator[None]:
        """Оборачивает operation в CB state-machine.

        При ``open`` бросает ``CircuitOpen`` без запроса к upstream.
        При exception — purgatory сам инкрементит failure_count.
        """
        async with self._breaker.guard():
            yield


_PUBLIC: Final = ("ClientCircuitBreaker", "CircuitOpen")
__all__ = _PUBLIC
