import json_tricks
from fastapi import Response

from app.infra.clients.logger import graylog_handler
from app.infra.clients.redis import redis_client
from app.infra.clients.smtp import smtp_client
from app.infra.clients.storage import s3_client
from app.infra.db.database import db_initializer
from app.utils.decorators.singleton import singleton
from app.utils.utils import utilities


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
        response_data = {
            "db": db_check,
            "redis": redis_check,
            "s3": s3_check,
            "s3_bucket": s3_bucket_check,
            "graylog": graylog_check,
            "smtp": smtp_check,
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
            content=json_tricks.dumps(
                response_body,
                extra_obj_encoders=[utilities.custom_json_encoder],
            ),
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

    async def check_s3(self):
        """
        Проверяет состояние S3.

        Returns:
            dict: Результат проверки состояния S3.
        """
        return await s3_client.check_connection()

    async def check_s3_bucket(self):
        """
        Проверяет наличие бакета в S3.

        Returns:
            dict: Результат проверки наличия бакета в S3.
        """
        return await s3_client.check_bucket_exists()

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
        return await smtp_client.test_connection()


health_check = HealthCheck()
