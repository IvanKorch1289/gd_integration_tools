from contextlib import asynccontextmanager
from typing import AsyncGenerator

from app.utils.decorators.singleton import singleton


__all__ = ("get_healthcheck_service",)


@singleton
class HealthCheck:

    async def check_all_services(self):
        """
        Checks the status of all supported services.

        Returns:
            dict: Comprehensive status report of all services.
        """
        db_check = await self.check_database()
        redis_check = await self.check_redis()
        s3_check = await self.check_s3()
        s3_bucket_check = await self.check_s3_bucket()
        graylog_check = await self.check_graylog()
        smtp_check = await self.check_smtp()
        rabbitmq_check = await self.check_rabbitmq()

        response_data = {
            "db": db_check,
            "redis": redis_check,
            "s3": all([s3_check, s3_bucket_check]),
            "graylog": graylog_check,
            "smtp": smtp_check,
            "rabbitmq": rabbitmq_check,
        }

        if all(response_data.values()):
            message = "All systems are operational."
            is_all_services_active = True
        else:
            message = "One or more components are not functioning properly."
            is_all_services_active = False

        return {
            "message": message,
            "is_all_services_active": is_all_services_active,
            "details": response_data,
        }

    async def check_database(self):
        """
        Verifies database connection status.

        Returns:
            dict: Database connection health check results.
        """
        from app.infra.db.database import db_initializer

        return await db_initializer.check_connection()

    async def check_redis(self):
        """
        Tests Redis connection availability.

        Returns:
            dict: Redis connection health check results.
        """
        from app.infra.clients.redis import redis_client

        return await redis_client.check_connection()

    async def check_s3(self):
        """
        Validates S3 storage connectivity.

        Returns:
            dict: S3 connection health check results.
        """
        from app.infra.clients.storage import s3_client

        return await s3_client.check_connection()

    async def check_s3_bucket(self):
        """
        Confirms existence of required S3 bucket.

        Returns:
            dict: S3 bucket verification results.
        """
        from app.infra.clients.storage import s3_client

        return await s3_client.check_bucket_exists()

    async def check_graylog(self):
        """
        Checks Graylog logging service status.

        Returns:
            dict: Graylog service health check results.
        """
        from app.infra.clients.logger import graylog_handler

        return await graylog_handler.check_connection()

    async def check_smtp(self):
        """
        Tests SMTP server connectivity.

        Returns:
            dict: SMTP server health check results.
        """
        from app.infra.clients.smtp import smtp_client

        return await smtp_client.test_connection()

    async def check_rabbitmq(self):
        """
        Verifies RabbitMQ message broker availability.

        Returns:
            dict: RabbitMQ connection health check results.
        """
        from aio_pika import connect

        from app.config.settings import settings

        try:
            connection = await connect(settings.queue.queue_url)

            await connection.close()

            return True
        except Exception:
            return False


@asynccontextmanager
async def get_healthcheck_service() -> AsyncGenerator[HealthCheck, None]:
    """
    Фабрика для создания MailService с изолированными зависимостями.
    """
    # Инициализируем клиенты здесь, если они требуют контекста
    health_check = HealthCheck()

    try:
        yield health_check
    finally:
        # Закрытие соединений клиентов, если требуется
        pass
