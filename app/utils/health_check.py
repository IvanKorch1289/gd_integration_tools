import json_tricks
from fastapi import Response

from app.celery.celery_config import celery_manager
from app.infra.db.database import db_initializer
from app.infra.logger import graylog_handler
from app.infra.queue import kafka_client
from app.infra.redis import redis_client
from app.infra.storage import s3_bucket_service_factory
from app.services.infra_services.mail import mail_service
from app.utils.decorators.singleton import singleton


__all__ = ("health_check",)


@singleton
class HealthCheck:

    async def check_all_services(self):
        """
        Проверяет состояние всех сервисов.

        Returns:
            dict: Результат проверки состояния всех сервисов.
        """
        db_check = await self.check_database()
        redis_check = await self.check_redis()
        s3_check = await self.check_s3()
        s3_bucket_check = await self.check_s3_bucket()
        graylog_check = await self.check_graylog()
        smtp_check = await self.check_smtp()
        celery_check = await self.check_celery()
        celery_queues_check = await self.check_celery_queues()
        celery_scheduler_check = await self.check_celery_scheduler()
        kafka_check = await self.check_kafka()
        response_data = {
            "db": db_check,
            "redis": redis_check,
            "s3": s3_check,
            "s3_bucket": s3_bucket_check,
            "graylog": graylog_check,
            "smtp": smtp_check,
            "celery": celery_check,
            "celery_queue": celery_queues_check,
            "celery_scheduler": celery_scheduler_check,
            "kafka": kafka_check,
        }

        if all(response_data.values()):
            status_code = 200
            message = "All systems are operational."
            is_all_services_active = True
        else:
            status_code = 500
            message = "One or more components are not functioning properly."
            is_all_services_active = False

        response_body = {
            "message": message,
            "is_all_services_active": is_all_services_active,
            "details": response_data,
        }

        return Response(
            content=json_tricks.dumps(response_body),
            media_type="application/json",
            status_code=status_code,
        )

    async def check_database(self):
        """
        Проверяет состояние базы данных.

        Returns:
            dict: Результат проверки состояния базы данных.
        """
        return await db_initializer.check_connection()

    async def check_redis(self):
        """
        Проверяет состояние Redis.

        Returns:
            dict: Результат проверки состояния Redis.
        """
        return await redis_client.check_connection()

    async def check_celery(self):
        """
        Проверяет состояние Celery.

        Returns:
            dict: Результат проверки состояния Celery.
        """
        return await celery_manager.check_connection()

    async def check_celery_queues(self):
        """
        Проверяет состояние очередей Celery.

        Returns:
            dict: Состояние очередей Celery.
        """
        return await celery_manager.check_queue_connection()

    async def check_celery_scheduler(self):
        """
        Проверяет состояние планировщика задач.

        Returns:
            dict: Результат проверки состояния планировщика задач.
        """
        return await celery_manager.check_beat_connection()

    async def check_s3(self):
        """
        Проверяет состояние S3.

        Returns:
            dict: Результат проверки состояния S3.
        """
        return await s3_bucket_service_factory().check_connection()

    async def check_s3_bucket(self):
        """
        Проверяет наличие бакета в S3.

        Returns:
            dict: Результат проверки наличия бакета в S3.
        """
        return await s3_bucket_service_factory().check_bucket_exists()

    async def check_graylog(self):
        """
        Проверяет состояние Graylog.

        Returns:
            dict: Результат проверки состояния Graylog.
        """
        return await graylog_handler.check_connection()

    async def check_smtp(self):
        """
        Проверяет состояние SMTP-сервера.

        Returns:
            dict: Результат проверки состояния SMTP-сервера.
        """
        return await mail_service.check_connection()

    async def check_kafka(self):
        """
        Проверяет состояние Kafka.

        Returns:
            dict: Результат проверки состояния Kafka.
        """
        return await kafka_client.healthcheck()


health_check = HealthCheck()
