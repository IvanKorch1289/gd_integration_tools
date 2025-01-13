import json
import sys
import traceback
from datetime import datetime
from functools import wraps
from typing import Any, Awaitable, Callable, Dict, List, TypeVar, Union

import aiosmtplib
import json_tricks
import socket
from fastapi import HTTPException, Response, status
from fastapi.responses import JSONResponse
from passlib.context import CryptContext
from pydantic import BaseModel, SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import session_manager
from backend.core.redis import redis
from backend.core.settings import settings
from backend.core.storage import s3_bucket_service_factory


T = TypeVar("T")
ParamsType = Dict[str, Any]


class Utilities:
    """Класс вспомогательных функций."""

    async def hash_password(self, password):
        if isinstance(password, SecretStr):
            unsecret_password = password.get_secret_value()
        else:
            unsecret_password = password
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return pwd_context.hash(unsecret_password)

    def caching(self, schema: BaseModel = None, expire: int = 600) -> Callable:
        """
        Фабрика декораторов для кэширования результатов функций в Redis.
        :param expire:return: Время жизни записи в кэше в секундах.
        :return: Декоратор для кэширования.
        """

        async def get_cached_data(key: str) -> Union[List[BaseModel], BaseModel, None]:
            """Функция для получения данных из кеша."""
            async with redis.connection() as r:
                cached_data = await r.get(key)
                if cached_data is not None:
                    try:
                        if isinstance(cached_data, bytes):
                            cached_data = cached_data.decode("utf-8")

                        decoded_data = json_tricks.loads(cached_data)

                        if isinstance(decoded_data, list):
                            return [json_tricks.loads(item) for item in decoded_data]
                        else:
                            return decoded_data
                    except (json.JSONDecodeError, ValueError) as exc:
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Ошибка при декодировании значения из кеша: {exc}",
                        )
            return None

        async def cache_data(
            key: str,
            data: Union[str, dict, List[BaseModel], BaseModel],
            *,
            expire: int = 3600,
        ) -> None:
            """
            Функция для сохранения данных в кеш.
            :param key: Ключ для кеша.
            :param data: Данные для сохранения в кеш.
            :param expire: Время жизни кеша в секундах.
            """

            def _encode(obj):
                if isinstance(obj, datetime) and not isinstance(obj, dict):
                    return obj.isoformat()
                elif isinstance(obj, BaseModel):
                    return obj.model_dump_json()
                return obj

            def custom_dumps(data):
                return json_tricks.dumps(data, extra_obj_encoders=[_encode])

            async with redis.connection() as r:
                if data is None:
                    return None
                if isinstance(data, JSONResponse):
                    encoded_data = data.body.decode("utf-8")
                else:
                    encoded_data = custom_dumps(data).encode("utf-8")
                await r.set(key, encoded_data, expire=expire)

        def decorator(
            func: Callable[[Any], Awaitable[Union[List[BaseModel], BaseModel]]]
        ) -> Callable[[Any], Awaitable[Union[List[BaseModel], BaseModel]]]:
            @wraps(func)
            async def wrapper(
                *args: Any, **kwargs: Any
            ) -> Union[List[BaseModel], BaseModel]:
                class_name = args[0].__class__.__name__
                method_name = func.__name__
                key = f"{class_name}.{method_name}.{kwargs}"
                cached_data = await get_cached_data(key)
                if cached_data is not None:
                    return cached_data

                result = await func(*args, **kwargs)
                await cache_data(key, result)

                return result

            return wrapper

        return decorator

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def health_check_database(self, session: AsyncSession) -> str:
        try:
            result = await session.execute(text("SELECT 1"))
            if result.scalar_one_or_none() != 1:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Database not connected",
                )
            return "Database connection is OK"
        except Exception as exc:
            traceback.print_exc(file=sys.stdout)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database not connected: {str(exc)}",
            )

    async def health_check_redis(self) -> str:
        try:
            async with redis.connection() as r:
                await r.ping()
            return "Redis connection is OK"
        except Exception as exc:
            traceback.print_exc(file=sys.stdout)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Redis not connected: {str(exc)}",
            )

    async def health_check_celery(self) -> str:
        from backend.core.tasks import celery_app

        try:
            result = celery_app.send_task(
                "test_task",
                args=["test"],
            )

            if result.get() == "test":
                return "Celery is working!"
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Celery not connected",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Celery not connected: {str(exc)}",
            )

    async def health_check_s3(self) -> str:
        s3_service = s3_bucket_service_factory()
        try:
            result = await s3_service.check_bucket_exists()
            if not result:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="S3 not connected",
                )
            return "S3 connection is OK"
        except Exception as exc:
            traceback.print_exc(file=sys.stdout)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"S3 not connected: {str(exc)}",
            )

    async def health_check_graylog(self) -> str:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(
                (
                    settings.logging_settings.log_host,
                    settings.logging_settings.log_udp_port,
                )
            )
            sock.sendall(b"Healthcheck test message")
            sock.close()
            return "Graylog connection is OK"
        except OSError as exc:
            traceback.print_exc(file=sys.stdout)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Graylog not connected: {str(exc)}",
            )

    async def health_check_smtp(self):
        hostname = settings.mail_settings.mail_hostname
        port = settings.mail_settings.mail_port
        use_tls = settings.mail_settings.mail_use_tls
        username = None if settings.app_debug else settings.mail_settings.mail_login
        password = None if settings.app_debug else settings.mail_settings.mail_login

        try:
            async with aiosmtplib.SMTP(
                hostname=hostname, port=port, use_tls=use_tls
            ) as smtp:
                if username and password:
                    await smtp.login(username, password)
                return "SMTP connection is OK"
        except Exception as exc:
            traceback.print_exc(file=sys.stdout)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"SMTP not connected: {str(exc)}",
            )

    async def health_check_all_services(self):
        db_check = await utilities.health_check_database()
        redis_check = await utilities.health_check_redis()
        s3_check = await utilities.health_check_s3()
        graylog_check = await utilities.health_check_graylog()
        smtp_check = await utilities.health_check_smtp()
        celery_check = await utilities.health_check_celery()

        response_data = {
            "db": db_check,
            "redis": redis_check,
            "s3": s3_check,
            "graylog": graylog_check,
            "smtp": smtp_check,
            "celery": celery_check,
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
            content=json.dumps(response_body),
            media_type="application/json",
            status_code=status_code,
        )

    async def send_email(self, to_email: str, subject: str, message: str):
        hostname = settings.mail_settings.mail_hostname
        port = settings.mail_settings.mail_port
        use_tls = settings.mail_settings.mail_use_tls
        username = None if settings.app_debug else settings.mail_settings.mail_login
        password = None if settings.app_debug else settings.mail_settings.mail_login

        try:
            async with aiosmtplib.SMTP(
                hostname=hostname, port=port, use_tls=use_tls
            ) as smtp:
                if username and password:
                    await smtp.login(username, password)

                await smtp.sendmail(
                    settings.mail_settings.mail_sender,
                    to_email,
                    f"Subject: {subject}\n\n{message}",
                )

            return JSONResponse({"status": "OK"})

        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)


utilities = Utilities()
