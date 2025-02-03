import logging
from typing import Optional

import graypy
import socket

from app.config.settings import LogStorageSettings, settings


__all__ = ("graylog_handler",)


class GraylogHandler:
    """Handles Graylog connection and logging configuration."""

    def __init__(self, config: LogStorageSettings):
        """
        Initialize Graylog handler.

        Args:
            config (LogStorageSettings): Logging configuration settings
        """
        self.config = config
        self.handler: Optional[logging.Handler] = None

    @property
    def enabled(self) -> bool:
        """Check if Graylog logging is enabled."""
        return bool(self.config.log_host and self.config.log_udp_port)

    def _connect(self) -> Optional[logging.Handler]:
        """
        Establish connection to Graylog server.

        Returns:
            Optional[logging.Handler]: Configured Graylog handler or None

        Raises:
            ConnectionError: If connection configuration is invalid
        """
        if not self.enabled:
            return None

        try:
            handler_class = (
                graypy.GELFTLSHandler
                if self.config.log_use_tls
                else graypy.GELFUDPHandler
            )
            handler = handler_class(
                self.config.log_host,
                self.config.log_udp_port,
                **(
                    {"ca_certs": self.config.log_ca_certs}
                    if self.config.log_use_tls
                    else {}
                ),
            )
            self.handler = handler
            return handler
        except Exception as exc:
            raise ConnectionError(f"Graylog connection failed: {exc}") from exc

    def _close(self) -> None:
        """Close Graylog connection resources."""
        if self.handler:
            self.handler.close()
            self.handler = None

    def check_connection(self) -> bool:
        """
        Verify Graylog server availability.

        Returns:
            bool: True if connection is successful

        Raises:
            ConnectionError: If connection test fails
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((self.config.log_host, self.config.log_udp_port))
                sock.sendall(b"Connection test")
            return True
        except OSError as exc:
            raise ConnectionError(
                f"Graylog connection check failed: {exc}"
            ) from exc


graylog_handler = GraylogHandler(config=settings.logging)
