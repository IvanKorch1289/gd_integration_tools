import asyncio
import builtins
from abc import ABC, abstractmethod
from asyncio import TimeoutError
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

from aiosmtplib import SMTP, SMTPAuthenticationError, SMTPException

from src.backend.core.config.settings import MailSettings, settings
from src.backend.core.utils.circuit_breaker import get_circuit_breaker

__all__ = ("BaseSmtpClient", "SmtpClient", "get_smtp_client", "smtp_client")


class BaseSmtpClient(ABC):
    """Абстрактный базовый класс для SMTP-клиентов."""

    @abstractmethod
    async def initialize_pool(self) -> None:
        """Инициализирует пул соединений."""

    @abstractmethod
    async def close_pool(self) -> None:
        """Закрывает пул соединений."""

    @abstractmethod
    async def get_connection(self) -> AsyncGenerator[Any]:
        """Контекстный менеджер для получения соединения."""

    @abstractmethod
    async def test_connection(self) -> bool:
        """Проверяет работоспособность соединения."""


class SmtpClient(BaseSmtpClient):
    """
    Расширенный SMTP-клиент с поддержкой пула соединений и механизмами отказоустойчивости.
    """

    def __init__(self, settings: MailSettings) -> None:
        """
        Инициализирует SMTP-клиент с настройками.

        Args:
            settings (MailSettings): Настройки для работы с SMTP.

        Raises:
            ValueError: Если настройки недействительны (отсутствуют хост или порт).
        """
        from src.backend.infrastructure.logging.factory import get_logger

        if not all([settings.host, settings.port]):
            raise ValueError("Неверная конфигурация SMTP")

        self.settings = settings
        self.logger = get_logger("smtp")
        self._pool_size = self.settings.connection_pool_size
        self._connection_pool: asyncio.Queue[SMTP] = asyncio.Queue(
            maxsize=self._pool_size
        )
        self._circuit_breaker = get_circuit_breaker()  # Инициализация CircuitBreaker

    async def __aenter__(self):
        """
        Вход в асинхронный контекстный менеджер для инициализации пула соединений.

        Returns:
            SmtpClient: Экземпляр SMTP-клиента.
        """
        await self.initialize_pool()
        return self

    async def __aexit__(self, exc_type, exc_val, _exc_tb) -> None:
        """
        Выход из асинхронного контекстного менеджера для корректного завершения работы.
        """
        await self.close_pool()

    async def initialize_pool(self) -> None:
        """
        Инициализирует и заполняет пул SMTP-соединений.

        Raises:
            RuntimeError: Если инициализация пула не удалась.
        """
        if self._connection_pool:
            self.logger.info("SMTP-пул уже инициализирован")
            return

        try:
            for _ in range(self._pool_size):
                connection = await self._create_connection()
                self._connection_pool.put_nowait(connection)

            self.logger.info(
                "Инициализирован пул SMTP с %s соединениями", self._pool_size
            )
        except Exception as exc:
            self.logger.critical(
                "Ошибка инициализации пула SMTP: %s", str(exc), exc_info=True
            )
            await self.close_pool()
            raise RuntimeError("Не удалось инициализировать пул соединений") from exc

    async def close_pool(self) -> None:
        """Корректно закрывает все соединения в пуле."""
        while not self._connection_pool.empty():
            connection = self._connection_pool.get_nowait()
            try:
                await connection.quit()
            except SMTPException as exc:
                self.logger.warning(
                    f"Ошибка при закрытии соединения: {exc!s}", exc_info=True
                )
        self.logger.info("Пул SMTP-соединений закрыт")

    async def _create_connection(self) -> SMTP:
        """
        Создает новое аутентифицированное SMTP-соединение с обработкой тайм-аутов.

        Returns:
            SMTP: Установленное SMTP-соединение.

        Raises:
            ConnectionError: Если соединение не удалось после нескольких попыток.
            TimeoutError: Если превышено время ожидания соединения.
        """
        # A2: async-timeout deprecated; используем нативный asyncio.timeout()
        # доступный с Python 3.11+ (проект требует 3.14).
        try:
            async with asyncio.timeout(self.settings.connect_timeout):
                smtp = SMTP(
                    hostname=self.settings.host,  # self.settings.smtp_url,
                    port=self.settings.port,
                    use_tls=self.settings.use_tls,
                    validate_certs=self.settings.validate_certs,
                    timeout=self.settings.command_timeout,
                )
                await smtp.connect()

                if self.settings.username and self.settings.password:
                    await smtp.login(self.settings.username, self.settings.password)
                return smtp
        except builtins.TimeoutError as exc:
            self.logger.error(
                f"Превышено время ожидания соединения: {exc!s}", exc_info=True
            )
            raise builtins.TimeoutError("Тайм-аут SMTP-соединения") from exc
        except SMTPAuthenticationError as exc:
            self.logger.error(f"Ошибка аутентификации: {exc!s}", exc_info=True)
            raise ConnectionError("Ошибка аутентификации SMTP") from exc
        except SMTPException as exc:
            self.logger.error(f"Ошибка соединения: {exc!s}", exc_info=True)
            raise ConnectionError("Ошибка SMTP-соединения") from exc

    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[SMTP]:
        """
        Контекстный менеджер для получения SMTP-соединения с поддержкой отказоустойчивости.

        Yields:
            SMTP: SMTP-соединение из пула или новое временное соединение.

        Raises:
            ConnectionError: Если сработал Circuit Breaker или соединение не удалось.
        """
        connection: SMTP | None = None
        temporary = False

        try:
            await self._circuit_breaker.check_state(
                max_failures=self.settings.circuit_breaker_max_failures,
                reset_timeout=self.settings.circuit_breaker_reset_timeout,
                exception_class=ConnectionError,
                error_message="SMTP-сервис недоступен (активирован Circuit Breaker)",
            )

            if not self._connection_pool.empty():
                connection = self._connection_pool.get_nowait()
            else:
                connection = await self._create_connection()
                temporary = True

            yield connection
            self._circuit_breaker.record_success()

        except Exception as exc:
            self._circuit_breaker.record_failure()
            self.logger.error(
                "Ошибка SMTP-соединения: %s: %s",
                type(exc).__name__,
                str(exc),
                exc_info=True,
            )
            raise
        finally:
            if connection is not None:
                await self._release_connection(
                    connection=connection, temporary=temporary
                )

    async def _acquire_connection(self) -> SMTP:
        """Получает SMTP-соединение из пула с повторными попытками через tenacity.

        K3 W1: замена custom retry-loop (range(3) + sleep) на make_async_retry.
        Retry выполняется при SMTPException / TimeoutError / ConnectionError / OSError
        с линейным backoff 1s → 2s → 3s (3 попытки суммарно).

        Returns:
            SMTP: Действительное SMTP-соединение.

        Raises:
            ConnectionError: Если все попытки соединения исчерпаны.
        """
        from src.backend.infrastructure.resilience.retry import make_async_retry

        @make_async_retry(
            max_attempts=3,
            initial_backoff=1.0,
            multiplier=1.0,
            max_backoff=3.0,
            on=(SMTPException, TimeoutError, ConnectionError, OSError),
        )
        async def _try_get() -> SMTP:
            """Одна попытка получить соединение из пула или создать новое."""
            self.logger.info(
                "Размер пула соединений: %d", self._connection_pool.qsize()
            )
            if self._connection_pool:
                return self._connection_pool.get_nowait()
            return await self._create_connection()

        try:
            return await _try_get()
        except (SMTPException, TimeoutError, ConnectionError, OSError) as exc:
            self.logger.error("Попытки SMTP-соединения исчерпаны: %s", exc)
            raise ConnectionError("Не удалось получить SMTP-соединение") from exc

    async def _release_connection(
        self, connection: SMTP, temporary: bool = False
    ) -> None:
        """Возвращает соединение в пул или закрывает его."""
        try:
            if connection.is_connected:
                await connection.noop()

                if not temporary and self._connection_pool.qsize() < self._pool_size:
                    self._connection_pool.put_nowait(connection)
                    return
        except SMTPException, OSError:
            self.logger.warning(
                "Ошибка проверки SMTP-соединения при возврате в пул", exc_info=True
            )

        try:
            await connection.quit()
        except SMTPException, OSError:
            self.logger.warning("Ошибка закрытия SMTP-соединения", exc_info=True)

    def metrics(self) -> dict[str, Any]:
        """
        Возвращает текущие метрики сервиса.

        Returns:
            dict[str, Any]: Словарь с метриками пула и состоянием Circuit Breaker.
        """
        return {
            "pool_capacity": f"{self._connection_pool.qsize()}/{self._pool_size}",
            "circuit_state": self._circuit_breaker.state,
            "active_connections": self._connection_pool.qsize(),
        }

    async def send_email(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
        from_address: str,
        html: bool = False,
    ) -> None:
        """Отправить email через SMTP-pool.

        Args:
            recipient: Адрес получателя.
            subject: Тема письма.
            body: Содержимое письма.
            from_address: Адрес отправителя.
            html: Если True, body интерпретируется как HTML.
        """
        from email.message import EmailMessage

        message = EmailMessage()
        message["From"] = from_address
        message["To"] = recipient
        message["Subject"] = subject
        if html:
            message.set_content(body, subtype="html")
        else:
            message.set_content(body)

        async with self.get_connection() as smtp:
            await smtp.send_message(message)

    async def test_connection(self) -> bool:
        """
        Выполняет end-to-end тест соединения с отправкой тестового письма.

        Returns:
            bool: True, если тестовое сообщение было принято сервером.
        """
        from email.message import EmailMessage

        try:
            async with self.get_connection() as smtp:
                message = EmailMessage()
                message["From"] = "test@service.check"
                message["To"] = "noreply@service.check"
                message["Subject"] = "SMTP Connectivity Test"
                message.set_content("SMTP service connectivity test")

                recipient_responses, _ = await smtp.send_message(
                    message,
                    sender="test@service.check",
                    recipients=["noreply@service.check"],
                )

            return all(resp.code == 250 for resp in recipient_responses.values())
        except Exception as exc:
            self.logger.error(f"Тест соединения не удался: {exc!s}", exc_info=True)
            return False


@lru_cache(maxsize=1)
def get_smtp_client() -> SmtpClient:
    """Lazy singleton ``SmtpClient`` (Wave 6.1).

    ``__init__`` создаёт ``asyncio.Queue`` — отложено до первого
    обращения, чтобы избежать привязки к event-loop'у времён импорта.
    """
    return SmtpClient(settings=settings.mail)


def __getattr__(name: str) -> Any:
    """Module-level lazy accessor для backward compat ``smtp_client``."""
    if name == "smtp_client":
        return get_smtp_client()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
