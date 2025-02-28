import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict

from aio_pika import connect

from app.config.settings import settings
from app.utils.decorators.singleton import singleton


__all__ = ("get_healthcheck_service",)


@singleton
class HealthCheck:
    """Сервис для комплексной проверки работоспособности системы.

    Осуществляет мониторинг всех критически важных компонентов приложения:
    - База данных
    - Кэш-хранилище (Redis)
    - Объектное хранилище (S3)
    - Система логирования (Graylog)
    - Почтовый сервис (SMTP)
    - Очередь сообщений (RabbitMQ)
    """

    async def check_all_services(self) -> Dict[str, Any]:
        """Выполняет комплексную проверку всех компонентов системы.

        Возвращает:
            Dict[str, Any]: Отчет о состоянии системы в формате:
                {
                    "message": общий статус,
                    "is_all_services_active": флаг общей доступности,
                    "details": детализированные результаты проверок
                }
        """
        # Параллельное выполнение проверок
        results = await asyncio.gather(
            self.check_database(),
            self.check_redis(),
            self.check_s3(),
            self.check_s3_bucket(),
            self.check_graylog(),
            self.check_smtp(),
            self.check_rabbitmq(),
        )

        # Формирование структуры ответа
        response_data = {
            "db": results[0],
            "redis": results[1],
            "s3": all(results[2:4]),
            "graylog": results[4],
            "smtp": results[5],
            "rabbitmq": results[6],
        }

        overall_status = all(response_data.values())

        return {
            "message": (
                "Все системы работают нормально"
                if overall_status
                else "Обнаружены проблемы в одном или нескольких компонентах"
            ),
            "is_all_services_active": overall_status,
            "details": response_data,
        }

    async def check_database(self) -> bool:
        """Проверяет доступность базы данных.

        Возвращает:
            bool: True если подключение успешно, False в случае ошибки
        """
        from app.infra.db.database import db_initializer

        return await db_initializer.check_connection()

    async def check_redis(self) -> bool:
        """Тестирует соединение с Redis-сервером.

        Возвращает:
            bool: Статус доступности Redis
        """
        from app.infra.clients.redis import redis_client

        return await redis_client.check_connection()

    async def check_s3(self) -> bool:
        """Проверяет доступность S3-хранилища.

        Возвращает:
            bool: Результат проверки соединения с объектным хранилищем
        """
        from app.infra.clients.storage import s3_client

        return await s3_client.check_connection()

    async def check_s3_bucket(self) -> bool:
        """Проверяет существование требуемого S3-бакета.

        Возвращает:
            bool: True если бакет существует, False в случае ошибки
        """
        from app.infra.clients.storage import s3_client

        return await s3_client.check_bucket_exists()

    async def check_graylog(self) -> bool:
        """Проверяет доступность сервиса логирования Graylog.

        Возвращает:
            bool: Статус подключения к Graylog
        """
        from app.infra.clients.logger import graylog_handler

        return await graylog_handler.check_connection()

    async def check_smtp(self) -> bool:
        """Тестирует соединение с SMTP-сервером.

        Возвращает:
            bool: Результат проверки почтового сервера
        """
        from app.infra.clients.smtp import smtp_client

        return await smtp_client.test_connection()

    async def check_rabbitmq(self) -> bool:
        """Проверяет доступность брокера сообщений RabbitMQ.

        Возвращает:
            bool: Статус подключения к RabbitMQ

        Выполняет:
            - Установку тестового соединения
            - Корректное закрытие подключения
        """
        try:
            connection = await connect(settings.queue.queue_url)
            await connection.close()
            return True
        except Exception:
            return False


@asynccontextmanager
async def get_healthcheck_service() -> AsyncGenerator[HealthCheck, None]:
    """Фабрика для создания экземпляра HealthCheck с управлением контекстом.

    Позволяет использовать конструкцию:
        async with get_healthcheck_service() as health_check:
            await health_check.check_all_services()

    Возвращает:
        AsyncGenerator[HealthCheck, None]: Асинхронный генератор экземпляра сервиса
    """
    yield HealthCheck()
