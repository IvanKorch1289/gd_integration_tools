"""Базовый класс для систем логирования.

Определяет ABC-контракт, который позволяет переключаться
между разными бэкендами (Graylog, Loki, Elasticsearch,
stdout, файлы) без изменения бизнес-кода.

Все бэкенды должны реализовать:
- configure() — настройка при старте
- get_logger(name) — получение именованного логгера
- shutdown() — корректное завершение
"""

from abc import ABC, abstractmethod
from typing import Any

__all__ = ("BaseLoggerBackend", "LoggerProtocol")


class LoggerProtocol(ABC):
    """Протокол логгера — минимальный интерфейс для бизнес-кода."""

    @abstractmethod
    def debug(self, msg: str, **kwargs: Any) -> None: ...

    @abstractmethod
    def info(self, msg: str, **kwargs: Any) -> None: ...

    @abstractmethod
    def warning(self, msg: str, **kwargs: Any) -> None: ...

    @abstractmethod
    def error(self, msg: str, **kwargs: Any) -> None: ...

    @abstractmethod
    def exception(self, msg: str, **kwargs: Any) -> None: ...

    @abstractmethod
    def bind(self, **kwargs: Any) -> "LoggerProtocol":
        """Возвращает логгер с привязанным контекстом."""
        ...


class BaseLoggerBackend(ABC):
    """ABC для бэкендов логирования.

    Реализации:
    - StructlogGraylogBackend — structlog + Graylog (GELF)
    - StdlibLoggingBackend — stdlib logging (текущая реализация)
    - (будущие) LokiBackend, ElasticBackend и т.д.
    """

    @abstractmethod
    def configure(self, **settings: Any) -> None:
        """Настраивает бэкенд при старте приложения."""
        ...

    @abstractmethod
    def get_logger(self, name: str) -> LoggerProtocol:
        """Возвращает именованный логгер."""
        ...

    @abstractmethod
    def shutdown(self) -> None:
        """Корректно завершает работу бэкенда."""
        ...
