"""Stdlib logging бэкенд — обёртка текущей реализации.

Обеспечивает обратную совместимость: все существующие логгеры
(app_logger, db_logger и др.) продолжают работать без изменений.
Используется по умолчанию, если structlog не установлен.
"""

import logging
from typing import Any

from src.backend.infrastructure.logging.base import BaseLoggerBackend, LoggerProtocol

__all__ = ("StdlibLoggingBackend",)


class StdlibLogger(LoggerProtocol):
    """Обёртка stdlib logging.Logger под LoggerProtocol."""

    def __init__(self, inner: logging.Logger) -> None:
        self._inner = inner

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._inner.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._inner.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._inner.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._inner.error(msg, *args, **kwargs)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._inner.exception(msg, *args, **kwargs)

    def bind(self, **kwargs: Any) -> "StdlibLogger":
        adapter = logging.LoggerAdapter(self._inner, kwargs)
        wrapped = StdlibLogger.__new__(StdlibLogger)
        wrapped._inner = adapter  
        return wrapped


class StdlibLoggingBackend(BaseLoggerBackend):
    """Бэкенд на stdlib logging.

    Делегирует LoggerManager из logging_service.py для legacy-имён,
    чтобы сохранить настроенные handlers (QueueListener, ContextFilter).
    Используется как fallback, если structlog недоступен.
    """

    def __init__(self) -> None:
        self._configured = False
        self._manager: Any | None = None

    def configure(self, **settings: Any) -> None:
        self._configured = True

    def _get_manager(self) -> Any:
        if self._manager is None:
            from src.backend.infrastructure.external_apis.logging_service import (
                get_log_manager,
            )

            self._manager = get_log_manager()
        return self._manager

    def get_logger(self, name: str) -> StdlibLogger:
        manager = self._get_manager()
        # Сопоставление canonical name → attribute name в LoggerManager.
        attr_map = {
            "application": "application_logger",
            "database": "database_logger",
            "storage": "storage_logger",
            "smtp": "smtp_logger",
            "scheduler": "scheduler_logger",
            "request": "request_logger",
            "tasks": "tasks_logger",
            "redis": "redis_logger",
            "stream": "stream_logger",
            "grpc": "grpc_logger",
        }
        attr = attr_map.get(name)
        if attr is not None:
            legacy = getattr(manager, attr, None)
            if legacy is not None:
                return StdlibLogger(legacy)
        return StdlibLogger(logging.getLogger(name))

    def shutdown(self) -> None:
        self._configured = False
