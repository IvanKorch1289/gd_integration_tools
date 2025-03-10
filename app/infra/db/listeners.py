from asyncio import create_task, sleep

from asyncpg import PostgresError
from sqlalchemy import event
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from time import monotonic

from app.config.constants import consts
from app.config.settings import settings
from app.utils.circuit_breaker import get_circuit_breaker
from app.utils.errors import DatabaseError
from app.utils.logging_service import db_logger


__all__ = ("DatabaseListener",)


class DatabaseListener:
    def __init__(self, async_engine):
        self.async_engine = async_engine
        self.async_session_factory = async_sessionmaker(
            bind=async_engine, expire_on_commit=False
        )
        self.circuit_breaker = get_circuit_breaker()
        self.settings = settings.database
        self.logger = db_logger

        self.register_async_handlers()
        self.register_sync_handlers()

    async def get_async_session(self) -> AsyncSession:
        return self.async_session_factory()

    def is_retriable_error(self, exception: Exception) -> bool:
        if isinstance(exception, (OperationalError, DBAPIError)):
            if isinstance(exception.orig, PostgresError):
                return exception.orig.sqlstate in consts.RETRIABLE_DB_CODES
        return False

    async def handle_async_error(self, exception_context):
        exc = exception_context.original_exception
        execution_context = exception_context.execution_context

        if not self.is_retriable_error(exc):
            return

        for attempt in range(1, self.settings.max_retries + 1):
            try:
                await self.circuit_breaker.check_state(
                    max_failures=self.settings.circuit_breaker_max_failures,
                    reset_timeout=self.settings.circuit_breaker_reset_timeout,
                    exception_class=DatabaseError,
                )

                async with self.get_async_session() as session:
                    async with session.begin():
                        result = await session.execute(
                            execution_context.statement,
                            execution_context.parameters,
                        )
                        self.circuit_breaker.record_success()
                        return result.scalars().all()

            except Exception as retry_exc:
                self.circuit_breaker.record_failure()
                self.logger.warning(
                    f"Retry attempt {attempt} failed: {str(retry_exc)}",
                    exc_info=True,
                )

                if attempt == self.settings.max_retries:
                    raise DatabaseError(
                        f"Database operation failed after {self.settings.max_retries} attempts"
                    ) from retry_exc

                await sleep(2**attempt * 0.5)

    def register_async_handlers(self):
        @event.listens_for(self.async_engine.sync_engine, "handle_error")
        def handle_async_error_wrapper(exception_context):
            if exception_context.is_disconnect:
                create_task(self.handle_async_error(exception_context))

    def register_sync_handlers(self):
        @event.listens_for(
            self.async_engine.sync_engine, "before_cursor_execute"
        )
        def before_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            # Сохраняем время начала выполнения запроса
            context._query_start_time = monotonic()

            self.logger.info(f"Выполнение SQL: {statement}")
            self.logger.debug(f"Параметры: {parameters}")

        @event.listens_for(
            self.async_engine.sync_engine, "after_cursor_execute"
        )
        def after_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            # Вычисляем время выполнения запроса
            if hasattr(context, "_query_start_time"):
                duration = monotonic() - context._query_start_time
                self.logger.debug(f"Query duration: {duration} seconds")

                # Логируем медленные запросы
                if duration > self.settings.slow_query_threshold:
                    self.logger.warning(
                        f"Slow query detected ({duration} seconds): {statement[:500]}"
                    )

            self.logger.info("SQL-запрос выполнен успешно")
