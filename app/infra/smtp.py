from collections import deque
from contextlib import asynccontextmanager
from typing import Deque

import aiosmtplib

from app.config.settings import MailSettings, settings
from app.utils.decorators.singleton import singleton
from app.utils.logging_service import mail_logger


__all__ = ("mail_service",)


@singleton
class MailService:
    """Email service with connection pooling and template support."""

    def __init__(self, settings: MailSettings):
        """
        Initialize mail service with configuration settings.

        Args:
            settings (MailSettings): Configuration parameters for mail service
        """
        self.settings = settings
        self._connection_pool: Deque[aiosmtplib.SMTP] = deque()
        self._pool_size = self.settings.mail_connection_pool_size

    async def __aenter__(self):
        """Async context manager entry point."""
        await self._initialize_pool()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit point."""
        await self._close_pool()

    async def _initialize_pool(self):
        """Initialize the SMTP connection pool."""
        try:
            for _ in range(self._pool_size):
                connection = await self._create_connection()
                self._connection_pool.append(connection)
                mail_logger.info("Successfully connected to SMTP server")
        except Exception as exc:
            raise RuntimeError(
                f"Failed to initialize SMTP connection pool: {str(exc)}"
            ) from exc

    async def _close_pool(self):
        """Close all connections in the pool."""
        try:
            while self._connection_pool:
                connection = self._connection_pool.pop()
                await connection.quit()
                mail_logger.info("SMTP server connections closed")
        except Exception as exc:
            mail_logger.error(f"Failed to close SMTP connection pool: {exc}")

    async def _create_connection(self) -> aiosmtplib.SMTP:
        """
        Create a new authenticated SMTP connection.

        Returns:
            aiosmtplib.SMTP: Established SMTP connection

        Raises:
            ConnectionError: If connection to SMTP server fails
        """
        try:
            smtp = aiosmtplib.SMTP(
                hostname=self.settings.mail_host,
                port=self.settings.mail_port,
                use_tls=self.settings.mail_use_tls,
            )
            await smtp.connect()
            if self.settings.mail_username and self.settings.mail_password:
                await smtp.login(
                    self.settings.mail_username,
                    self.settings.mail_password,
                )
            return smtp
        except Exception as exc:
            raise ConnectionError(f"SMTP connection failed: {exc}") from exc

    @asynccontextmanager
    async def get_connection(self):
        """
        Context manager for acquiring SMTP connections from the pool.

        Yields:
            aiosmtplib.SMTP: SMTP connection from pool or new temporary connection

        Example:
            async with mail_service.get_connection() as smtp:
                await smtp.send_message(msg)
        """
        if not self._connection_pool:
            connection = await self._create_connection()
            yield connection
            await connection.quit()
        else:
            connection = self._connection_pool.pop()
            try:
                yield connection
            finally:
                self._connection_pool.appendleft(connection)

    async def check_connection(self) -> bool:
        """
        Verify SMTP server availability.

        Returns:
            bool: True if connection is successful

        Raises:
            ConnectionError: If connection check fails
        """
        try:
            async with self.get_connection() as smtp:
                await smtp.noop()
            return True
        except Exception as exc:
            raise ConnectionError(
                f"SMTP connection check failed: {exc}"
            ) from exc


mail_service = MailService(settings=settings.mail)
