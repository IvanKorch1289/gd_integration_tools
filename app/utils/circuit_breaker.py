from datetime import datetime, timedelta
from typing import Optional, Type


__all__ = ("CircuitBreaker", "get_circuit_breaker")


class CircuitBreaker:
    """Универсальная реализация Circuit Breaker с поддержкой разных типов ошибок."""

    def __init__(self):
        self.state: str = "CLOSED"
        self.failure_count: int = 0
        self.last_failure_time: Optional[datetime] = None

    def _is_timeout_expired(self, reset_timeout: int) -> bool:
        """Проверяет, истекло ли время таймаута для сброса состояния.

        Args:
            reset_timeout: Время в секундах до сброса состояния.

        Returns:
            bool: True, если таймаут истек, иначе False.
        """
        if self.last_failure_time is None:
            return False
        return datetime.now() > self.last_failure_time + timedelta(
            seconds=reset_timeout
        )

    async def check_state(
        self,
        max_failures: int,
        reset_timeout: int,
        exception_class: Type[Exception] = Exception,
        error_message: str = "Circuit Breaker triggered",
    ) -> None:
        """Проверяет и обновляет состояние Circuit Breaker.

        Args:
            max_failures: Максимальное количество ошибок до срабатывания.
            reset_timeout: Время в секундах до сброса состояния.
            exception_class: Класс исключения для вызова.
            error_message: Сообщение об ошибке.
        """
        if self.state == "OPEN" and self._is_timeout_expired(reset_timeout):
            self.state = "HALF-OPEN"
            self.failure_count = 0

        if self.failure_count >= max_failures:
            self.state = "OPEN"
            self.last_failure_time = datetime.now()
            raise exception_class(error_message)

    def record_failure(self) -> None:
        """Фиксирует неудачный запрос."""
        self.failure_count += 1

    def record_success(self) -> None:
        """Сбрасывает Circuit Breaker при успешном запросе."""
        if self.state == "HALF-OPEN":
            self.state = "CLOSED"
        self.failure_count = 0

    async def is_blocked(self) -> bool:
        """Проверяет состояние без вызова исключения.

        Returns:
            bool: True, если Circuit Breaker в состоянии OPEN и таймаут не истек.
        """
        return self.state == "OPEN" and not self._is_timeout_expired(
            reset_timeout=30
        )


def get_circuit_breaker() -> CircuitBreaker:
    """Создает и возвращает экземпляр Circuit Breaker.

    Returns:
        CircuitBreaker: Экземпляр Circuit Breaker.
    """
    return CircuitBreaker()
