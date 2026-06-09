"""Stdlib logging бэкенд — обёртка текущей реализации.

Обеспечивает обратную совместимость: все существующие логгеры
(app_logger, db_logger и др.) продолжают работать без изменений.
Используется по умолчанию, если structlog не установлен.

Sprint 38: get_logger больше не делегирует в logging_service — это
устраняет import-time regression из-за загрузки settings/Vault при
первом вызове get_logger() в холодном процессе.
"""

import logging
from typing import Any

from src.backend.infrastructure.logging.base import BaseLoggerBackend, LoggerProtocol

__all__ = ("StdlibLoggingBackend",)


class StdlibLogger(LoggerProtocol):
    """Обёртка stdlib logging.Logger под LoggerProtocol.

    Sprint 60 W2 — добавлен ``.name`` property для обратной совместимости
    с callers, которые обращаются к ``logger.name`` напрямую (ожидая
    stdlib ``logging.Logger.name``). Также добавлены ``.level``/``.handlers``
    /``.parent``/propagation controls — минимальный API surface для
    миграции существующего кода.
    """

    def __init__(self, inner: logging.Logger) -> None:
        self._inner = inner

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def level(self) -> int:
        return self._inner.level

    @property
    def handlers(self) -> list[logging.Handler]:
        return self._inner.handlers

    @property
    def parent(self) -> logging.Logger | None:
        return self._inner.parent

    def setLevel(self, level: int) -> None:  # noqa: N802 — stdlib API
        self._inner.setLevel(level)

    def addHandler(self, handler: logging.Handler) -> None:  # noqa: N802
        self._inner.addHandler(handler)

    def removeHandler(self, handler: logging.Handler) -> None:  # noqa: N802
        self._inner.removeHandler(handler)

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

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._inner.critical(msg, *args, **kwargs)

    def log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
        self._inner.log(level, msg, *args, **kwargs)

    def isEnabledFor(self, level: int) -> bool:  # noqa: N802
        return self._inner.isEnabledFor(level)

    def bind(self, **kwargs: Any) -> "StdlibLogger":
        adapter = logging.LoggerAdapter(self._inner, kwargs)
        wrapped = StdlibLogger.__new__(StdlibLogger)
        wrapped._inner = adapter
        return wrapped


class StdlibLoggingBackend(BaseLoggerBackend):
    """Бэкенд на stdlib logging.

    Используется как fallback, если structlog недоступен или не
    сконфигурирован явно. Не тянет legacy :mod:`logging_service`
    при получении логгера — это критично для ``import time``
    (Sprint 38 startup-time regression fix).
    """

    def __init__(self) -> None:
        self._configured = False

    def configure(self, **settings: Any) -> None:
        self._configured = True

    def get_logger(self, name: str) -> StdlibLogger:
        return StdlibLogger(logging.getLogger(name))

    def shutdown(self) -> None:
        self._configured = False
