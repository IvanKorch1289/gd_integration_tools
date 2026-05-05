"""Circuit Breaker — единый адаптер поверх core.interfaces.CircuitBreaker.

Предоставляет совместимый API для http.py и smtp.py
(async check_state + record_failure/success), делегируя
state machine в interfaces.CircuitBreaker.

Использование::

    cb = get_circuit_breaker(reset_timeout=30)
    await cb.check_state(max_failures=5, exception_class=ConnectionError)
    cb.record_success()
"""

from __future__ import annotations

from src.backend.core.interfaces import CircuitBreaker as _CircuitBreakerImpl
from src.backend.core.interfaces import CircuitBreakerConfig

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
