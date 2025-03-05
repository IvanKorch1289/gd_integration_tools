from asyncio import TimeoutError, sleep
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Deque, Dict

from aiosmtplib import SMTP, SMTPAuthenticationError, SMTPException

from app.config.settings import MailSettings, settings
from app.utils.circuit_breaker import get_circuit_breaker
from app.utils.decorators.singleton import singleton


__all__ = (
    "smtp_client",
    "SmtpClient",
)


@singleton
class SmtpClient:
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
        from collections import deque

        from app.utils.logging_service import smtp_logger

        if not all([settings.host, settings.port]):
            raise ValueError("Неверная конфигурация SMTP")

        self.settings = settings
        self.logger = smtp_logger
        self._connection_pool: Deque[SMTP] = deque()
        self._pool_size = self.settings.connection_pool_size
        self._circuit_breaker = (
            get_circuit_breaker()
        )  # Инициализация CircuitBreaker

    async def __aenter__(self):
        """
        Вход в асинхронный контекстный менеджер для инициализации пула соединений.

        Returns:
            SmtpClient: Экземпляр SMTP-клиента.
        """
        await self.initialize_pool()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
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
        try:
            for _ in range(self._pool_size):
                connection = await self._create_connection()
                self._connection_pool.append(connection)
            self.logger.info(
                f"Инициализирован пул SMTP с {self._pool_size} соединениями"
            )
        except Exception as exc:
            self.logger.critical(
                f"Ошибка инициализации пула SMTP: {str(exc)}", exc_info=True
            )
            raise RuntimeError(
                "Не удалось инициализировать пул соединений"
            ) from exc

    async def close_pool(self) -> None:
        """Корректно закрывает все соединения в пуле."""
        while self._connection_pool:
            connection = self._connection_pool.pop()
            try:
                await connection.quit()
            except SMTPException as exc:
                self.logger.warning(
                    f"Ошибка при закрытии соединения: {str(exc)}",
                    exc_info=True,
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
        from async_timeout import timeout

        try:
            async with timeout(self.settings.connect_timeout):
                smtp = SMTP(
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
        except TimeoutError as exc:
            self.logger.error(
                f"Превышено время ожидания соединения: {str(exc)}",
                exc_info=True,
            )
            raise TimeoutError("Тайм-аут SMTP-соединения") from exc
        except SMTPAuthenticationError as exc:
            self.logger.error(
                f"Ошибка аутентификации: {str(exc)}", exc_info=True
            )
            raise ConnectionError("Ошибка аутентификации SMTP") from exc
        except SMTPException as exc:
            self.logger.error(f"Ошибка соединения: {str(exc)}", exc_info=True)
            raise ConnectionError("Ошибка SMTP-соединения") from exc

    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[SMTP, None]:
        """
        Контекстный менеджер для получения SMTP-соединения с поддержкой отказоустойчивости.

        Yields:
            SMTP: SMTP-соединение из пула или новое временное соединение.

        Raises:
            ConnectionError: Если сработал Circuit Breaker или соединение не удалось.
        """
        try:
            # Проверяем состояние Circuit Breaker
            await self._circuit_breaker.check_state(
                max_failures=self.settings.circuit_breaker_max_failures,  # Максимальное количество ошибок
                reset_timeout=self.settings.circuit_breaker_reset_timeout,  # Таймаут сброса
                exception_class=ConnectionError,
                error_message="SMTP-сервис недоступен (активирован Circuit Breaker)",
            )
            connection = await self._acquire_connection()
            yield connection
            # Фиксируем успешный запрос
            self._circuit_breaker.record_success()
        except Exception as exc:
            # Фиксируем ошибку
            self._circuit_breaker.record_failure()
            self.logger.error(
                f"Ошибка соединения: {type(exc).__name__}, {str(exc)}",
                exc_info=True,
            )
            raise ConnectionError(
                "Не удалось получить SMTP-соединение"
            ) from exc
        finally:
            if connection:
                await self._release_connection(connection)

    async def _acquire_connection(self) -> SMTP:
        """
        Получает соединение с логикой повторных попыток.

        Returns:
            SMTP: Действительное SMTP-соединение.

        Raises:
            ConnectionError: Если соединение не удалось установить.
        """
        for attempt in range(3):
            try:
                self.logger.info(
                    f"Размер пула соединений: {len(self._connection_pool)}"
                )
                if self._connection_pool:
                    return self._connection_pool.pop()
                return await self._create_connection()
            except Exception:
                if attempt == 2:
                    self.logger.error("Попытки соединения исчерпаны")
                    raise
                delay = 1 * (attempt + 1)
                self.logger.warning(
                    f"Повторная попытка соединения через {delay} сек..."
                )
                await sleep(delay)
        raise ConnectionError("Не удалось получить SMTP-соединение")

    async def _release_connection(self, connection: SMTP) -> None:
        """Возвращает соединение в пул или закрывает его."""
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

    def metrics(self) -> Dict[str, Any]:
        """
        Возвращает текущие метрики сервиса.

        Returns:
            Dict[str, Any]: Словарь с метриками пула и состоянием Circuit Breaker.
        """
        return {
            "pool_capacity": f"{len(self._connection_pool)}/{self._pool_size}",
            "circuit_state": self._circuit_breaker.state,
            "active_connections": sum(
                1 for conn in self._connection_pool if conn.is_connected
            ),
        }

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

            return all(
                resp.code == 250 for resp in recipient_responses.values()
            )
        except Exception as exc:
            self.logger.error(
                f"Тест соединения не удался: {str(exc)}", exc_info=True
            )
            return False


smtp_client = SmtpClient(settings=settings.mail)
