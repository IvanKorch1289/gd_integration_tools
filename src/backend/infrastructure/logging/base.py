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
    """Logger protocol — minimal interface for business code.

    Signature matches stdlib logging.Logger with printf-style formatting
    and keyword args for structlog binding.
    """

    @abstractmethod
    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log debug message.

        Args:
            msg: Message format string.
            *args: Format arguments.
            **kwargs: Additional keyword arguments.
        """
        ...

    @abstractmethod
    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log info message.

        Args:
            msg: Message format string.
            *args: Format arguments.
            **kwargs: Additional keyword arguments.
        """
        ...

    @abstractmethod
    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log warning message.

        Args:
            msg: Message format string.
            *args: Format arguments.
            **kwargs: Additional keyword arguments.
        """
        ...

    @abstractmethod
    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log error message.

        Args:
            msg: Message format string.
            *args: Format arguments.
            **kwargs: Additional keyword arguments.
        """
        ...

    @abstractmethod
    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log critical message.

        Args:
            msg: Message format string.
            *args: Format arguments.
            **kwargs: Additional keyword arguments.
        """
        ...

    @abstractmethod
    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log exception with traceback.

        Args:
            msg: Message format string.
            *args: Format arguments.
            **kwargs: Additional keyword arguments.
        """
        ...

    @abstractmethod
    def bind(self, **kwargs: Any) -> "LoggerProtocol":
        """Return logger with bound context.

        Args:
            **kwargs: Context key-value pairs.

        Returns:
            Logger with bound context.
        """
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
