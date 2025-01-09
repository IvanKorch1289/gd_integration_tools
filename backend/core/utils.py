import json
import sys
import traceback
from datetime import datetime
from functools import wraps
from typing import Any, Awaitable, Callable, Dict, List, TypeVar, Union

import json_tricks
import socket
from fastapi import HTTPException, status
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
            return {"check": "Database connection is OK"}
        except Exception:
            traceback.print_exc(file=sys.stdout)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not connected",
            )

    async def health_check_redis(self) -> str:
        try:
            async with redis.connection() as r:
                await r.ping()
            return {"check": "Redis connection is OK"}
        except Exception:
            traceback.print_exc(file=sys.stdout)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Redis not connected",
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
            return {"check": "S3 connection is OK"}
        except Exception:
            traceback.print_exc(file=sys.stdout)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="S3 not connected",
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
            return {"check": "Graylog connection is OK"}
        except OSError:
            traceback.print_exc(file=sys.stdout)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Graylog not connected",
            )


utilities = Utilities()
