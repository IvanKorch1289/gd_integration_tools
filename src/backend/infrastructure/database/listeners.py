from time import monotonic

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from src.infrastructure.external_apis.logging_service import db_logger

__all__ = ("DatabaseListener",)


class DatabaseListener:
    """
    SQLAlchemy listeners для telemetry и безопасного логирования запросов.

    Ответственность:
    - измерение времени выполнения SQL;
    - логирование медленных запросов;
    - логирование ошибок драйвера/соединения;
    - без retry и без повторного выполнения SQL.
    """

    def __init__(
        self, async_engine: AsyncEngine, db_name: str, slow_query_threshold: float
    ):
        self.async_engine = async_engine
        self.db_name = db_name
        self.slow_query_threshold = slow_query_threshold
        self.logger = db_logger

        self.register_handlers()

    def register_handlers(self) -> None:
        """
        Регистрирует обработчики SQLAlchemy для sync_engine,
        лежащего под AsyncEngine.
        """
        sync_engine = self.async_engine.sync_engine

        @event.listens_for(sync_engine, "before_cursor_execute")
        def before_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            """
            Сохраняет время старта запроса.
            """
            context._query_start_time = monotonic()

        @event.listens_for(sync_engine, "after_cursor_execute")
        def after_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            """
            Логирует длительность запроса и помечает slow queries.
            """
            started_at = getattr(context, "_query_start_time", None)
            if started_at is None:
                return

            duration = monotonic() - started_at

            payload = {
                "db_name": self.db_name,
                "duration_sec": round(duration, 6),
                "executemany": executemany,
                "statement_preview": statement[:500] if statement else None,
            }

            if duration >= self.slow_query_threshold:
                self.logger.warning("Slow SQL query detected", extra=payload)
            else:
                self.logger.debug("SQL query executed", extra=payload)

        @event.listens_for(sync_engine, "handle_error")
        def handle_error(exception_context):
            """
            Логирует ошибку драйвера/соединения.

            Важно:
            параметры запроса целиком не логируются,
            чтобы не тянуть чувствительные данные в Graylog.
            """
            self.logger.error(
                "Database driver error",
                extra={
                    "db_name": self.db_name,
                    "is_disconnect": exception_context.is_disconnect,
                    "statement_preview": (
                        exception_context.statement[:500]
                        if exception_context.statement
                        else None
                    ),
                },
                exc_info=exception_context.original_exception,
            )
