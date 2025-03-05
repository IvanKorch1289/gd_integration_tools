from sqlalchemy.event import listen
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config.settings import settings
from app.utils.circuit_breaker import CircuitBreaker, get_circuit_breaker
from app.utils.errors import DatabaseError
from app.utils.logging_service import db_logger


__all__ = ("DatabaseListener",)


class DatabaseListener:
    """Класс для централизованной обработки ошибок и логирования SQL-запросов."""

    def __init__(self, async_engine):
        """
        Инициализация слушателя.

        Args:
            engine: Движок SQLAlchemy (синхронный или асинхронный).
            circuit_breaker: Экземпляр CircuitBreaker для обработки ошибок.

            max_retries: Максимальное количество повторных попыток.
        """
        self.async_engine: AsyncEngine = async_engine
        self.circuit_breaker: CircuitBreaker = get_circuit_breaker()
        self.settings = settings.database
        self.logger = db_logger
        self.register_error_handler()
        self.register_logging_events()

    def get_engines(self):
        """Определяет движки БД.

        Returns:
            engines: список движков БД.
        """
        engines = []

        if hasattr(self.async_engine, "sync_engine"):
            engines.append(self.async_engine.sync_engine)
        return engines

    def is_retriable_error(self, exception: Exception) -> bool:
        """Определяет, является ли ошибка повторяемой.

        Args:
            exception: Исключение, которое нужно проверить.

        Returns:
            bool: True, если ошибка повторяемая, иначе False.
        """
        if isinstance(exception, OperationalError):
            error_code = getattr(exception.orig, "sqlite_error_code", None)
            retriable_codes = [
                "5",
                "6",
                "8",
                "11",
            ]  # Busy, Locked, Readonly, Corrupt
            return str(error_code) in retriable_codes
        return False

    async def handle_db_error(self, exception_context):
        """Обработчик ошибок с повторными попытками.

        Args:
            exception_context: Контекст исключения SQLAlchemy.

        Returns:
            Результат выполнения запроса, если успешно.

        Raises:
            DatabaseError: Если операция завершилась неудачей после всех попыток.
        """
        exc = exception_context.original_exception
        execution_context = exception_context.execution_context

        if not self.is_retriable_error(exc):
            return  # Не повторять для критических ошибок

        for attempt in range(self.settings.circuit_breaker_max_failures):
            try:
                self.circuit_breaker.record_failure()
                await self.circuit_breaker.check_state(
                    max_failures=self.settings.circuit_breaker_max_failures,
                    reset_timeout=self.settings.circuit_breaker_reset_timeout,
                    exception_class=DatabaseError,
                )

                # Повторное выполнение оригинального запроса
                if execution_context:
                    result = execution_context._execute_wrapper(
                        execution_context.cursor,
                        execution_context.statement,
                        execution_context.parameters,
                        execution_context,
                    )
                    self.circuit_breaker.record_success()
                    return result

            except Exception as retry_exc:
                if attempt == self.settings.circuit_breaker_max_failures - 1:
                    self.circuit_breaker.record_failure()
                    raise DatabaseError(
                        f"Operation failed after {self.settings.circuit_breaker_max_failures} attempts"
                    ) from retry_exc

    def register_error_handler(self):
        """Регистрирует обработчик ошибок для синхронного и асинхронного движков."""
        for eng in self.get_engines():
            listen(eng, "handle_error", self.handle_db_error, retval=True)

    def register_logging_events(self):
        """Регистрирует обработчики событий для логирования SQL-запросов."""

        def before_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            self.logger.info("Выполнение SQL: %s", statement)
            self.logger.debug("Параметры: %s", parameters)

        def after_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            self.logger.info("SQL-запрос выполнен успешно")

        for eng in self.get_engines():
            listen(
                eng,
                "before_cursor_execute",
                before_cursor_execute,
            )
            listen(
                eng,
                "after_cursor_execute",
                after_cursor_execute,
            )
