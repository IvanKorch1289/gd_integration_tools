import json
from functools import wraps
from typing import Any, Awaitable, Callable, Dict, TypeVar

from fastapi import HTTPException, status
from passlib.context import CryptContext
from pydantic import SecretStr

from gd_advanced_tools.core.redis import redis


T = TypeVar("T")
ParamsType = Dict[str, Any]


class Utilities:
    """Класс вспомогательных функций."""

    async def hash_password(self, password):
        if isinstance(password, SecretStr):
            unsecret_password = password.get_secret_value()
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return await pwd_context.hash(unsecret_password)

    def caching(cls, expire: int = 600) -> Callable:
        """
        Фабрика декораторов для кэширования результатов функций в Redis.
        :param expire: Время жизни записи в кэше в секундах.
        :return: Декоратор для кэширования.
        """

        def decorator(
            func: Callable[[ParamsType], Awaitable[T]]
        ) -> Callable[[ParamsType], Awaitable[T]]:
            @wraps(func)
            async def wrapper(params: ParamsType) -> T:
                r = await redis.get_redis()

                key = f"{func.__name__}:{json.dumps(params)}"

                value = await r.get(key)
                if value is not None:
                    try:
                        return json.loads(value)
                    except Exception as e:
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Error decoding cached value: {e}",
                        )

                result = await func(**params)
                await r.set(key, json.dumps(result), expire=expire)
                return result

            return wrapper

        return decorator


utilities = Utilities()
