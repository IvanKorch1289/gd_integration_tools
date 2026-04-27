"""Единый per-client Circuit Breaker для infrastructure-клиентов.

IL1.4 (ADR-022): до этой фазы CB был только на HTTP + SMTP. Теперь доступен
единый helper поверх ``aiocircuitbreaker``, который применяется также для
Redis / MongoDB / Kafka — с thresholds из `PoolingProfile`.

Использование:

    class RedisConnector(ClientMetricsMixin, InfrastructureClient):
        def __init__(self, settings):
            super().__init__(name="redis", pooling=settings.pooling)
            self._breaker = ClientCircuitBreaker.from_profile(
                name=self.name, profile=self.pooling,
            )

        async def get(self, key):
            async with self._breaker.guard():
                async with self.track("GET"):
                    return await self._redis.get(key)

State machine:
  ``closed`` → при failure_threshold подряд failures → ``open``.
  ``open`` → через ``recovery_timeout`` секунд → ``half_open``.
  ``half_open`` → первый успех возвращает в ``closed``; failure — снова ``open``.

Метрики: обновляется gauge `infra_client_circuit_state{client,host}` через
`client_metrics.record_circuit_state()` на каждом переходе.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator, Final

if TYPE_CHECKING:
    from src.core.config.pooling import PoolingProfile


_logger = logging.getLogger(__name__)


class CircuitOpen(Exception):
    """Бросается клиентом, когда breaker в состоянии OPEN."""


class _FallbackBreaker:
    """Внутренний fallback на случай, если aiocircuitbreaker не установлен.

    Реализует минимально достаточный API state-machine через ручной счётчик
    последовательных failures. Используется только как dev-safety-net;
    в production aiocircuitbreaker должен быть установлен.
    """

    def __init__(self, *, failure_threshold: int, recovery_timeout: float) -> None:
        import time

        self._threshold = failure_threshold
        self._recovery = recovery_timeout
        self._failures = 0
        self._state = "closed"
        self._open_until = 0.0
        self._now = time.monotonic

    @property
    def state(self) -> str:
        if self._state == "open" and self._now() >= self._open_until:
            self._state = "half_open"
        return self._state

    def record_success(self) -> None:
        self._failures = 0
        self._state = "closed"

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._state = "open"
            self._open_until = self._now() + self._recovery

    def is_open(self) -> bool:
        return self.state == "open"


def _build_backend(failure_threshold: int, recovery_timeout: float) -> object:
    """Создать экземпляр aiocircuitbreaker.CircuitBreaker или fallback."""
    try:
        from aiocircuitbreaker import CircuitBreaker  # type: ignore[import-untyped]

        return CircuitBreaker(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            expected_exception=Exception,
        )
    except ImportError:
        _logger.warning(
            "aiocircuitbreaker not installed, using fallback _FallbackBreaker"
        )
        return _FallbackBreaker(
            failure_threshold=failure_threshold, recovery_timeout=recovery_timeout
        )


class ClientCircuitBreaker:
    """Обёртка над backend CB + client_metrics reporting.

    В отличие от прямого использования `aiocircuitbreaker.CircuitBreaker`,
    этот класс:

    1. Знает имя клиента (для Prometheus labels).
    2. Автоматически обновляет gauge `infra_client_circuit_state`.
    3. Поддерживает fallback при отсутствии `aiocircuitbreaker`.
    4. Предоставляет удобный `async with .guard():` API.
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
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._backend = _build_backend(failure_threshold, recovery_timeout)
        # Публикуем initial state.
        self._last_state: str | None = None
        self._publish_state("closed")

    @classmethod
    def from_profile(
        cls, *, name: str, profile: "PoolingProfile", host: str = "default"
    ) -> "ClientCircuitBreaker":
        """Создать CB из `PoolingProfile` (circuit_threshold + circuit_recovery_s)."""
        return cls(
            name=name,
            host=host,
            failure_threshold=profile.circuit_threshold,
            recovery_timeout=profile.circuit_recovery_s,
        )

    # -- State -------------------------------------------------------

    def _current_state(self) -> str:
        state = getattr(self._backend, "state", None) or getattr(
            self._backend, "current_state", None
        )
        if state is None:
            # aiocircuitbreaker exposes as attribute or property; normalize.
            state = "closed"
        # Нормализация имён: некоторые версии используют `open`/`closed`/`half_open`.
        return str(state)

    def _publish_state(self, state: str) -> None:
        if state == self._last_state:
            return
        self._last_state = state
        try:
            from src.infrastructure.observability.client_metrics import (
                record_circuit_state,
            )

            # Привести к Literal[closed, open, half_open].
            normalized = state if state in ("closed", "open", "half_open") else "closed"
            record_circuit_state(
                client=self.name,
                host=self.host,
                state=normalized,  # type: ignore[arg-type]
            )
        except ImportError:
            pass

    def is_open(self) -> bool:
        state = self._current_state()
        return state == "open"

    # -- Guard API ---------------------------------------------------

    @asynccontextmanager
    async def guard(self) -> AsyncIterator[None]:
        """Оборачивает operation в CB state-machine.

        При ``open`` бросает ``CircuitOpen`` без запроса к upstream.
        При exception во время operation — помечает failure + публикует новый
        state.
        """
        if self.is_open():
            self._publish_state("open")
            raise CircuitOpen(
                f"Circuit breaker '{self.name}' is OPEN (host={self.host})"
            )
        try:
            yield
        except Exception:
            # Backend запомнит failure — вызвать его, если есть публичный метод.
            self._record_failure()
            self._publish_state(self._current_state())
            raise
        else:
            self._record_success()
            self._publish_state(self._current_state())

    def _record_success(self) -> None:
        method = getattr(self._backend, "record_success", None)
        if callable(method):
            method()

    def _record_failure(self) -> None:
        method = getattr(self._backend, "record_failure", None)
        if callable(method):
            method()


_PUBLIC: Final = ("ClientCircuitBreaker", "CircuitOpen")
__all__ = _PUBLIC
