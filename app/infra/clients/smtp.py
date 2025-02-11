from collections import deque
from contextlib import asynccontextmanager
from email.message import EmailMessage
from typing import Any, AsyncGenerator, Deque, Dict

import aiosmtplib
import asyncio
from async_timeout import timeout

from app.config.settings import MailSettings, settings
from app.utils.decorators.singleton import singleton
from app.utils.logging_service import smtp_logger


__all__ = (
    "smtp_client",
    "SmtpClient",
)


@singleton
class SmtpClient:
    """Advanced SMTP client service with connection pooling and fault tolerance features."""

    def __init__(self, settings: MailSettings) -> None:
        """
        Initialize the mail service with configuration settings.

        Args:
            settings: Configuration parameters for SMTP operations

        Raises:
            ValueError: If provided settings are invalid
        """
        if not all([settings.host, settings.port]):
            raise ValueError("Invalid SMTP configuration")

        self.settings = settings
        self.logger = smtp_logger
        self._connection_pool: Deque[aiosmtplib.SMTP] = deque()
        self._pool_size = self.settings.connection_pool_size
        self._circuit_opened = False
        self._circuit_timeout = self.settings.circuit_breaker_timeout

    async def __aenter__(self):
        """Async context manager entry for pool initialization."""
        await self.initialize_pool()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit for graceful shutdown."""
        await self.close_pool()

    async def initialize_pool(self) -> None:
        """
        Initialize and populate the SMTP connection pool.

        Raises:
            RuntimeError: If pool initialization fails
        """
        try:
            for _ in range(self._pool_size):
                connection = await self._create_connection()
                self._connection_pool.append(connection)
            self.logger.info(
                f"Initialized SMTP pool with {self._pool_size} connections"
            )
        except Exception as exc:
            self.logger.critical(
                "SMTP pool initialization failed", exc_info=True
            )
            raise RuntimeError("Failed to initialize connection pool") from exc

    async def close_pool(self) -> None:
        """Gracefully close all connections in the pool."""
        while self._connection_pool:
            connection = self._connection_pool.pop()
            try:
                await connection.quit()
            except aiosmtplib.SMTPException:
                self.logger.warning("Error closing connection", exc_info=True)
        self.logger.info("SMTP connection pool closed")

    async def _create_connection(self) -> aiosmtplib.SMTP:
        """
        Create a new authenticated SMTP connection with timeout handling.

        Returns:
            aiosmtplib.SMTP: Established SMTP connection

        Raises:
            ConnectionError: If connection fails after retries
            TimeoutError: If connection timeout exceeds
        """
        try:
            async with timeout(self.settings.connect_timeout):
                smtp = aiosmtplib.SMTP(
                    hostname=self.settings.host,
                    port=self.settings.port,
                    use_tls=self.settings.use_tls,
                    validate_certs=self.settings.validate_certs,
                    timeout=self.settings.command_timeout,
                )
                await smtp.connect()

                if self.settings.username and self.settings.password:
                    await smtp.login(
                        self.settings.username,
                        self.settings.password,
                    )
                return smtp
        except asyncio.TimeoutError as exc:
            self.logger.error("Connection timeout exceeded", exc_info=True)
            raise TimeoutError("SMTP connection timeout") from exc
        except aiosmtplib.SMTPAuthenticationError as exc:
            self.logger.error("Authentication failed", exc_info=True)
            raise ConnectionError("SMTP authentication error") from exc
        except aiosmtplib.SMTPException as exc:
            self.logger.error("Connection failed", exc_info=True)
            raise ConnectionError("SMTP connection error") from exc

    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[aiosmtplib.SMTP, None]:
        """
        Context manager for acquiring SMTP connections with fault tolerance.

        Yields:
            aiosmtplib.SMTP: SMTP connection from pool or new temporary connection

        Raises:
            ConnectionError: If circuit breaker is active or connection fails
        """
        if self._circuit_opened:
            raise ConnectionError(
                "SMTP service unavailable (circuit breaker active)"
            )
        connection = None
        try:
            connection = await self._acquire_connection()
            yield connection
        except Exception as exc:
            self.logger.error(
                f"Connection error: {type(exc).__name__}", exc_info=True
            )
            await self._handle_connection_error(exc)
            raise ConnectionError("Failed to acquire SMTP connection") from exc
        finally:
            if connection:
                await self._release_connection(connection)

    async def _acquire_connection(self) -> aiosmtplib.SMTP:
        """
        Acquire connection with retry logic.

        Returns:
            aiosmtplib.SMTP: Valid SMTP connection

        Raises:
            ConnectionError: If connection cannot be established
        """
        for attempt in range(3):
            try:
                self.logger.info(
                    f"Connection pool size: {len(self._connection_pool)}"
                )
                if self._connection_pool:
                    return self._connection_pool.pop()
                return await self._create_connection()
            except Exception:
                if attempt == 2:
                    self.logger.error("Connection attempts exhausted")
                    raise
                delay = 1 * (attempt + 1)
                self.logger.warning(f"Retrying connection in {delay}s...")
                await asyncio.sleep(delay)
        raise ConnectionError("Failed to acquire SMTP connection")

    async def _release_connection(self, connection: aiosmtplib.SMTP) -> None:
        """Release connection back to pool or close it."""
        try:
            if connection.is_connected:
                await connection.noop()
                if len(self._connection_pool) < self._pool_size:
                    self._connection_pool.appendleft(connection)
                    return
        except Exception:
            pass

        try:
            await connection.quit()
        except Exception:
            pass

    async def _handle_connection_error(self, exc: Exception) -> None:
        """Handle connection errors and manage circuit breaker state."""
        self.logger.warning("Connection error occurred", exc_info=True)

        if isinstance(
            exc,
            (
                aiosmtplib.SMTPConnectError,
                aiosmtplib.SMTPServerDisconnected,
                asyncio.TimeoutError,
            ),
        ):
            self._circuit_opened = True
            self.logger.critical("Circuit breaker triggered")

            await self.reset_pool()
            await asyncio.sleep(self._circuit_timeout)

            self._circuit_opened = False
            self.logger.info("Circuit breaker reset")

    async def reset_pool(self) -> None:
        """Reset the entire connection pool."""
        await self.close_pool()
        await self.initialize_pool()
        self.logger.info("Connection pool reset completed")

    def metrics(self) -> Dict[str, Any]:
        """
        Get current service metrics.

        Returns:
            Dictionary with pool statistics and circuit state
        """
        return {
            "pool_capacity": f"{len(self._connection_pool)}/{self._pool_size}",
            "circuit_state": "OPEN" if self._circuit_opened else "CLOSED",
            "active_connections": sum(
                1 for conn in self._connection_pool if conn.is_connected
            ),
        }

    async def test_connection(self) -> bool:
        """
        Perform end-to-end connection test with test email.

        Returns:
            bool: True if test message was accepted by server
        """
        try:
            async with self.get_connection() as smtp:
                # Создаем сообщение через стандартный email модуль
                message = EmailMessage()
                message["From"] = "test@service.check"
                message["To"] = "noreply@service.check"
                message["Subject"] = "SMTP Connectivity Test"
                message.set_content("SMTP service connectivity test")

                # Отправка с явным указанием отправителя и получателей
                recipient_responses, _ = await smtp.send_message(
                    message,
                    sender="test@service.check",
                    recipients=["noreply@service.check"],
                )

            return all(
                resp.code == 250 for resp in recipient_responses.values()
            )
        except Exception:
            self.logger.error("Connection test failed", exc_info=True)
            return False


smtp_client = SmtpClient(settings=settings.mail)
