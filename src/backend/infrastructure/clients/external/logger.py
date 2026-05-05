import logging
from functools import lru_cache
from logging import Handler
from typing import Any

from src.core.config.settings import LogStorageSettings, settings

__all__ = ("graylog_handler", "GraylogHandler", "get_graylog_handler")

_logger = logging.getLogger(__name__)


class GraylogHandler:
    """Обработчик для подключения к Graylog и настройки логирования."""

    def __init__(self, config: LogStorageSettings):
        """
        Инициализирует обработчик Graylog.

        Args:
            config (LogStorageSettings): Настройки логирования для Graylog.
        """
        self.config = config
        self.handler: Handler | None = None

    @property
    def enabled(self) -> bool:
        """Проверяет, включено ли логирование в Graylog.

        Returns:
            bool: True, если логирование включено, иначе False.
        """
        return bool(self.config.host and self.config.udp_port)

    def connect(self) -> Handler | None:
        """
        Устанавливает соединение с сервером Graylog.

        Returns:
            logging.Handler | None: Настроенный обработчик Graylog или None.

        Raises:
            ConnectionError: Если конфигурация соединения недействительна.
        """
        if not self.enabled:
            return None

        try:
            import graypy  # type: ignore[import-not-found]
        except ImportError:
            _logger.warning(
                "graypy не установлен — Graylog-обработчик отключён "
                "(установите: pip install graypy для активации)"
            )
            return None

        try:
            handler_class = (
                graypy.GELFTLSHandler if self.config.use_tls else graypy.GELFUDPHandler
            )
            handler = handler_class(
                self.config.host,
                self.config.udp_port,
                **({"ca_certs": self.config.ca_bundle} if self.config.use_tls else {}),
            )
            self.handler = handler
            return handler
        except Exception as exc:
            raise ConnectionError(f"Ошибка подключения к Graylog: {str(exc)}") from exc

    def close(self) -> None:
        """Закрывает ресурсы соединения с Graylog."""
        if self.handler:
            self.handler.close()
            self.handler = None

    async def check_connection(self) -> bool:
        """
        Проверяет доступность сервера Graylog.

        Returns:
            bool: True, если соединение успешно.

        Raises:
            ConnectionError: Если проверка соединения не удалась.
        """
        import socket

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((self.config.host, self.config.udp_port))
                sock.sendall(b"Connection test")
            return True
        except OSError as exc:
            raise ConnectionError(
                f"Ошибка проверки соединения с Graylog: {str(exc)}"
            ) from exc


@lru_cache(maxsize=1)
def get_graylog_handler() -> GraylogHandler:
    """Lazy singleton ``GraylogHandler`` (Wave 6.1).

    Создание handler'а отложено до первого обращения, чтобы избежать
    сетевого resolve в момент import (включая ``LogStorageSettings``
    может тянуть DNS).
    """
    return GraylogHandler(config=settings.logging)


def __getattr__(name: str) -> Any:
    """Module-level lazy accessor для backward compat ``graylog_handler``."""
    if name == "graylog_handler":
        return get_graylog_handler()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
