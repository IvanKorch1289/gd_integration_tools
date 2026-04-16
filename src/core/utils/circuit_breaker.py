"""Circuit Breaker для защиты от каскадных сбоев.

Реализует паттерн Circuit Breaker с тремя состояниями:
CLOSED → OPEN → HALF-OPEN → CLOSED.
"""

import time

__all__ = ("CircuitBreaker", "get_circuit_breaker")


class CircuitBreaker:
    """Circuit Breaker с поддержкой configurable timeout.

    Использует ``time.monotonic()`` вместо ``datetime.now()``
    для корректной работы при изменении системного времени.

    Attrs:
        reset_timeout: Время (сек) до перехода OPEN → HALF-OPEN.
    """

    def __init__(self, *, reset_timeout: int = 30) -> None:
        self.state: str = "CLOSED"
        self.failure_count: int = 0
        self.last_failure_time: float = 0.0
        self.reset_timeout = reset_timeout

    def _is_timeout_expired(self) -> bool:
        """Проверяет, истёк ли reset_timeout."""
        if self.last_failure_time == 0.0:
            return False
        return time.monotonic() - self.last_failure_time > self.reset_timeout

    async def check_state(
        self,
        max_failures: int,
        reset_timeout: int | None = None,
        exception_class: type[Exception] = Exception,
        error_message: str = "Circuit Breaker triggered",
    ) -> None:
        """Проверяет и обновляет состояние.

        Args:
            max_failures: Порог ошибок для срабатывания.
            reset_timeout: Таймаут сброса (по умолчанию
                из конструктора).
            exception_class: Класс исключения.
            error_message: Сообщение ошибки.

        Raises:
            exception_class: При срабатывании breaker.
        """
        if reset_timeout is not None:
            self.reset_timeout = reset_timeout

        if self.state == "OPEN" and self._is_timeout_expired():
            self.state = "HALF-OPEN"
            self.failure_count = 0

        if self.failure_count >= max_failures:
            self.state = "OPEN"
            self.last_failure_time = time.monotonic()
            raise exception_class(error_message)

    def record_failure(self) -> None:
        """Фиксирует неудачный запрос."""
        self.failure_count += 1

    def record_success(self) -> None:
        """Сбрасывает breaker при успешном запросе."""
        if self.state == "HALF-OPEN":
            self.state = "CLOSED"
        self.failure_count = 0

    async def is_blocked(self) -> bool:
        """Проверяет блокировку без исключения.

        Returns:
            ``True`` если OPEN и timeout не истёк.
        """
        return self.state == "OPEN" and not self._is_timeout_expired()


def get_circuit_breaker(
    *, reset_timeout: int = 30
) -> CircuitBreaker:
    """Создаёт экземпляр Circuit Breaker.

    Args:
        reset_timeout: Таймаут сброса в секундах.

    Returns:
        Экземпляр ``CircuitBreaker``.
    """
    return CircuitBreaker(reset_timeout=reset_timeout)
