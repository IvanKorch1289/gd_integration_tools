"""Stdlib logging бэкенд — обёртка текущей реализации.

Обеспечивает обратную совместимость: все существующие логгеры
(app_logger, db_logger и др.) продолжают работать без изменений.
Используется по умолчанию, если structlog не установлен.
"""

import logging
from typing import Any

from app.infrastructure.logging.base import BaseLoggerBackend, LoggerProtocol

__all__ = ("StdlibLoggingBackend",)


class StdlibLogger(LoggerProtocol):
    """Обёртка stdlib logging.Logger под LoggerProtocol."""

    def __init__(self, inner: logging.Logger) -> None:
        self._inner = inner

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._inner.debug(msg, extra=kwargs)

    def info(self, msg: str, **kwargs: Any) -> None:
        self._inner.info(msg, extra=kwargs)

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._inner.warning(msg, extra=kwargs)

    def error(self, msg: str, **kwargs: Any) -> None:
        self._inner.error(msg, extra=kwargs)

    def exception(self, msg: str, **kwargs: Any) -> None:
        self._inner.exception(msg, extra=kwargs)

    def bind(self, **kwargs: Any) -> "StdlibLogger":
        adapter = logging.LoggerAdapter(self._inner, kwargs)
        wrapped = StdlibLogger.__new__(StdlibLogger)
        wrapped._inner = adapter  # type: ignore[assignment]
        return wrapped


class StdlibLoggingBackend(BaseLoggerBackend):
    """Бэкенд на stdlib logging.

    Делегирует LoggerManager из logging_service.py.
    Используется как fallback, если structlog недоступен.
    """

    def __init__(self) -> None:
        self._configured = False

    def configure(self, **settings: Any) -> None:
        self._configured = True

    def get_logger(self, name: str) -> StdlibLogger:
        return StdlibLogger(logging.getLogger(name))

    def shutdown(self) -> None:
        self._configured = False
