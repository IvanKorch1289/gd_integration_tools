import json
import sys
import traceback
from functools import wraps
from typing import Any, Awaitable, Callable, Dict, List, TypeVar, Union

from fastapi import HTTPException, Response, status
from fastapi.responses import JSONResponse
from passlib.context import CryptContext
from pydantic import BaseModel, SecretStr

from backend.core.redis import redis


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
                        decoded_data = json.loads(cached_data)

                        if isinstance(decoded_data, list):
                            return [json.loads(item) for item in decoded_data]
                        elif isinstance(decoded_data, str):
                            return json.loads(decoded_data)
                        return decoded_data
                    except (json.JSONDecodeError, ValueError) as e:
                        traceback.print_exc(file=sys.stdout)
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Ошибка при декодировании значения из кеша: {e}",
                        )
            return None

        async def cache_data(
            key: str,
            data: Union[str, dict, List[BaseModel], BaseModel] = None,
            *,
            expire: int = 3600,
        ) -> None:
            """
            Функция для сохранения данных в кеш.
            :param key: Ключ для кеша.
            :param data: Данные для сохранения в кеш.
            :param expire: Время жизни кеша в секундах.
            """
            async with redis.connection() as r:
                print(data)
                if data is None:
                    return None

                if isinstance(data, str):
                    encoded_data = data.encode("utf-8")
                elif isinstance(data, Exception):
                    encoded_data = str(data).encode("utf-8")
                elif isinstance(data, JSONResponse) or isinstance(data, Response):
                    decoded_body = data.body.decode("utf-8").strip()
                    if decoded_body:
                        try:
                            encoded_data = json.dumps(json.loads(decoded_body)).encode(
                                "utf-8"
                            )
                        except json.JSONDecodeError:
                            encoded_data = decoded_body.encode("utf-8")
                    else:
                        return None
                elif isinstance(data, dict):
                    encoded_data = json.dumps(data).encode("utf-8")
                elif isinstance(data, BaseModel):
                    encoded_data = data.model_dump_json().encode("utf-8")
                elif isinstance(data, list):
                    encoded_data = json.dumps(
                        [
                            (
                                item.model_dump_json()
                                if isinstance(item, BaseModel)
                                else item
                            )
                            for item in data
                        ]
                    ).encode("utf-8")
                else:
                    raise TypeError(f"Неподдерживаемый тип данных: {type(data)}")

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


utilities = Utilities()
