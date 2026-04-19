"""Фабрика логирования — единая точка получения логгеров.

Автоматически выбирает бэкенд:
- structlog (если установлен) — структурированные JSON-логи в Graylog
- stdlib logging (fallback) — текущая реализация через LoggerManager

Использование:
    from app.infrastructure.logging.factory import get_logger

    logger = get_logger("application")
    logger.info("Order created", order_id=123, user_id="abc")

Переключение бэкенда:
    from app.infrastructure.logging.factory import configure_logging

    # structlog → Graylog
    configure_logging(backend="structlog")

    # stdlib (по умолчанию)
    configure_logging(backend="stdlib")
"""

from typing import Any

from app.infrastructure.logging.base import BaseLoggerBackend, LoggerProtocol

__all__ = ("get_logger", "configure_logging", "shutdown_logging")

_backend: BaseLoggerBackend | None = None


def _create_backend(name: str) -> BaseLoggerBackend:
    if name == "structlog":
        try:
            from app.infrastructure.logging.structlog_backend import (
                StructlogGraylogBackend,
            )
            return StructlogGraylogBackend()
        except ImportError:
            pass

    from app.infrastructure.logging.stdlib_backend import StdlibLoggingBackend
    return StdlibLoggingBackend()


def configure_logging(
    backend: str = "auto",
    **settings: Any,
) -> BaseLoggerBackend:
    """Настраивает систему логирования.

    Args:
        backend: ``"structlog"``, ``"stdlib"`` или ``"auto"``
            (structlog если установлен, иначе stdlib).
        **settings: Передаются в backend.configure().

    Returns:
        Настроенный бэкенд.
    """
    global _backend

    if _backend is not None:
        _backend.shutdown()

    if backend == "auto":
        try:
            import structlog  # noqa: F401
            backend = "structlog"
        except ImportError:
            backend = "stdlib"

    _backend = _create_backend(backend)
    _backend.configure(**settings)
    return _backend


def get_logger(name: str) -> LoggerProtocol:
    """Возвращает логгер по имени.

    Если бэкенд ещё не настроен — создаёт stdlib fallback.

    Args:
        name: Имя логгера (например ``"application"``,
            ``"database"``, ``"redis"``).

    Returns:
        Логгер, совместимый с LoggerProtocol.
    """
    global _backend

    if _backend is None:
        _backend = _create_backend("stdlib")
        _backend.configure()

    return _backend.get_logger(name)


def shutdown_logging() -> None:
    """Корректно завершает систему логирования."""
    global _backend
    if _backend is not None:
        _backend.shutdown()
        _backend = None
