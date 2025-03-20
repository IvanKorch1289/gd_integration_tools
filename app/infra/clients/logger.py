from logging import Handler

from app.config.settings import LogStorageSettings, settings


__all__ = ("graylog_handler",)


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

        import graypy

        try:
            handler_class = (
                graypy.GELFTLSHandler
                if self.config.use_tls
                else graypy.GELFUDPHandler
            )
            handler = handler_class(
                self.config.host,
                self.config.udp_port,
                **(
                    {"ca_certs": self.config.ca_bundle}
                    if self.config.use_tls
                    else {}
                ),
            )
            self.handler = handler
            return handler
        except Exception as exc:
            raise ConnectionError(
                f"Ошибка подключения к Graylog: {str(exc)}"
            ) from exc

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


graylog_handler = GraylogHandler(config=settings.logging)
