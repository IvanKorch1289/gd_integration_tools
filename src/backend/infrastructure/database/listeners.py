from __future__ import annotations

from time import monotonic
from types import TracebackType

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from src.backend.core.logging import get_logger

db_logger = get_logger("database")

__all__ = (
    "DatabaseListener",
    "SanitizedDbError",
    "sanitize_db_error_text",
    "sanitized_exc_info",
)

#: Маркер блока со значениями параметров, который SQLAlchemy дописывает
#: в текст исключения (``[parameters: ('ivan@example.com',)]``).
_PARAMS_MARKER = "[parameters:"

#: Маска вместо значений параметров.
_PARAMS_MASK = "[parameters: ***]"


def _params_block_end(text: str, start: int) -> int:
    """Найти конец блока ``[parameters: ...]`` с учётом кавычек и скобок.

    Args:
        text: Исходный текст ошибки.
        start: Индекс начала маркера ``[parameters:``.

    Returns:
        Индекс первого символа после блока (``len(text)`` — если блок
        не закрыт).
    """
    index = start + len(_PARAMS_MARKER)
    depth = 0
    quote: str | None = None
    while index < len(text):
        char = text[index]
        if quote is not None:
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            if char == "]" and depth == 0:
                return index + 1
            depth -= 1
        index += 1
    return len(text)


def sanitize_db_error_text(text: str) -> str:
    """Маскировать значения bind-параметров в тексте ошибки БД.

    SQLAlchemy дописывает в текст исключения фактические значения
    параметров запроса (``[parameters: ('ivan@example.com',)]``). Это PII:
    блок уезжал в ``exchange.error`` (через ``DatabaseError``) и в лог.
    Маскируется только блок параметров — SQL и остальная диагностика
    сохраняются.

    Args:
        text: Текст исключения (или произвольный текст).

    Returns:
        Текст без значений параметров запроса.
    """
    if _PARAMS_MARKER not in text:
        return text

    chunks: list[str] = []
    cursor = 0
    while True:
        start = text.find(_PARAMS_MARKER, cursor)
        if start == -1:
            chunks.append(text[cursor:])
            break
        chunks.append(text[cursor:start])
        chunks.append(_PARAMS_MASK)
        cursor = _params_block_end(text, start)
    return "".join(chunks)


class SanitizedDbError(Exception):
    """Обёртка DB-ошибки для логирования: текст без значений параметров."""


def sanitized_exc_info(
    exc: BaseException,
) -> tuple[type[BaseException], BaseException, TracebackType | None]:
    """Собрать ``exc_info`` для логирования без PII параметров запроса.

    ``logger.error(..., exc_info=True)`` печатает исходный текст
    исключения — вместе с блоком ``[parameters: ...]``. Здесь собирается
    кортеж с очищенным текстом; исходный traceback сохраняется.

    Args:
        exc: Исходное исключение.

    Returns:
        Кортеж ``(type, value, traceback)`` для ``logger.error(exc_info=...)``.
    """
    message = f"{type(exc).__name__}: {sanitize_db_error_text(str(exc))}"
    return (type(exc), SanitizedDbError(message), exc.__traceback__)


class DatabaseListener:
    """SQLAlchemy listeners для telemetry и безопасного логирования запросов.

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
        """Регистрирует обработчики SQLAlchemy для sync_engine,
        лежащего под AsyncEngine.
        """
        sync_engine = self.async_engine.sync_engine

        @event.listens_for(sync_engine, "before_cursor_execute")
        def before_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            """Сохраняет время старта запроса."""
            context._query_start_time = monotonic()

        @event.listens_for(sync_engine, "after_cursor_execute")
        def after_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            """Логирует длительность запроса и помечает slow queries."""
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
            """Логирует ошибку драйвера/соединения.

            Важно:
            параметры запроса целиком не логируются,
            чтобы не тянуть чувствительные данные в Graylog.

            Wave 16 / X4 (ADR-0383): исходный текст исключения содержит
            блок ``[parameters: ('ivan@example.com',)]`` — он маскируется
            (``sanitize_db_error_text``), иначе PII утекает в лог.
            """
            original = exception_context.original_exception
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
                exc_info=sanitized_exc_info(original) if original else None,
            )
