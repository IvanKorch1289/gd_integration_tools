import json
import sys
import traceback
from functools import wraps
from typing import Any, Awaitable, Callable, Dict, List, TypeVar, Union

from fastapi import HTTPException, status
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

    def caching(self, schema: BaseModel, expire: int = 600) -> Callable:
        """
        Фабрика декораторов для кэширования результатов функций в Redis.
        :param expire:return: Время жизни записи в кэше в секундах.
        :return: Декоратор для кэширования.
        """

        async def get_cached_data(key: str) -> Union[List[BaseModel], BaseModel]:
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

        async def cache_data(key: str, data: Union[List[BaseModel], BaseModel]) -> None:
            """Функция для сохранения данных в кеш."""
            if not data:
                return None
            async with redis.connection() as r:
                if isinstance(data, list):
                    encoded_data = [
                        item.model_dump_json() if not isinstance(item, str) else item
                        for item in data
                    ]
                elif not isinstance(data, dict):
                    encoded_data = data.model_dump_json()
                await r.set(key, json.dumps(encoded_data), expire=expire)

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
