"""Circuit Breaker — единый адаптер поверх core.interfaces.CircuitBreaker.

.. deprecated:: S38
    ``core.utils.circuit_breaker`` устарел. Используйте
    :class:`src.backend.core.resilience.breaker.CircuitBreaker` (canonical
    от V22.10.2 wave 1, ADR-005). Этот модуль остаётся как backwards-compat
    shim и будет удалён в V24+.

Предоставляет совместимый API для http.py и smtp.py
(async check_state + record_failure/success), делегируя
state machine в interfaces.CircuitBreaker.

Использование::

    cb = get_circuit_breaker(reset_timeout=30)
    await cb.check_state(max_failures=5, exception_class=ConnectionError)
    cb.record_success()
"""

from __future__ import annotations

import warnings

# Deprecation: S38 W2 T2.2 — v9 plan P2.3 (CB consolidation)
# Canonical: src.backend.core.resilience.breaker.CircuitBreaker
# Removal: V24+
warnings.warn(
    "core.utils.circuit_breaker is deprecated since S38; "
    "use src.backend.core.resilience.breaker.CircuitBreaker instead. "
    "See .hermes/plans/S38_W2_P23_CB_audit.md for migration guide.",
    DeprecationWarning,
    stacklevel=2,
)

from src.backend.core.interfaces import CircuitBreaker as _CircuitBreakerImpl  # noqa: E402,I001
from src.backend.core.interfaces import CircuitBreakerConfig  # noqa: E402

__all__ = ("CircuitBreaker", "get_circuit_breaker")


class CircuitBreaker:
    """Adapter: async check_state API поверх interfaces.CircuitBreaker.

    http.py и smtp.py вызывают:
      - await cb.check_state(max_failures=..., exception_class=...)
      - cb.record_failure()
      - cb.record_success()

    Внутри делегирует в interfaces.CircuitBreaker с полной
    state machine (CLOSED → OPEN → HALF_OPEN → CLOSED).
    """

    def __init__(self, *, reset_timeout: int = 30, name: str = "default") -> None:
        self._impl = _CircuitBreakerImpl(
            name, CircuitBreakerConfig(recovery_timeout=float(reset_timeout))
        )
        self._name = name

    async def check_state(
        self,
        max_failures: int,
        reset_timeout: int | None = None,
        exception_class: type[Exception] = Exception,
        error_message: str = "Circuit Breaker triggered",
    ) -> None:
        """Проверяет состояние и бросает исключение если CB открыт.

        Args:
            max_failures: Порог ошибок для срабатывания.
            reset_timeout: Таймаут до перехода OPEN → HALF_OPEN.
            exception_class: Класс исключения при срабатывании.
            error_message: Сообщение ошибки.

        Raises:
            exception_class: Если CB открыт и таймаут не истёк.
        """
        if reset_timeout is not None:
            self._impl._config.recovery_timeout = float(reset_timeout)
        self._impl._config.failure_threshold = max_failures

        if not self._impl.allow_request():
            raise exception_class(error_message)

    def record_failure(self) -> None:
        """Фиксирует неудачный запрос."""
        self._impl.record_failure()

    def record_success(self) -> None:
        """Сбрасывает breaker при успешном запросе."""
        self._impl.record_success()

    async def is_blocked(self) -> bool:
        """Проверяет блокировку без исключения."""
        return self._impl.state.value == "open"

    @property
    def state(self) -> str:
        """Текущее состояние: CLOSED / OPEN / HALF_OPEN."""
        return self._impl.state.value.upper()

    @property
    def failure_count(self) -> int:
        """Число зафиксированных failures с момента последнего reset."""
        return self._impl._failure_count


def get_circuit_breaker(
    *, reset_timeout: int = 30, name: str = "default"
) -> CircuitBreaker:
    """Создаёт экземпляр Circuit Breaker (adapter).

    Args:
        reset_timeout: Таймаут сброса в секундах.
        name: Имя breaker для логирования.

    Returns:
        CircuitBreaker adapter.
    """
    return CircuitBreaker(reset_timeout=reset_timeout, name=name)
