from functools import wraps

import redis.asyncio as redis
from fastapi import HTTPException, Request, Response
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter

from app.config.settings import settings


__all__ = (
    "init_limiter",
    "route_limiting",
)


async def init_limiter():
    """
    Инициализирует Redis и FastAPILimiter.

    Returns:
        None
    """
    redis_connection = redis.from_url(
        f"{settings.redis.redis_url}/{settings.redis.redis_db_queue}",
        encoding="utf-8",
        decode_responses=True,
    )
    await FastAPILimiter.init(redis_connection)


class RouteLimiter:
    """
    Класс для лимитирования маршрутов.

    Атрибуты:
        times (int): Количество разрешенных запросов.
        seconds (int): Временной интервал в секундах.
    """

    def __init__(
        self,
        times: int = settings.auth.auth_rate_limit,
        seconds: int = settings.auth.auth_rate_time_measure_seconds,
    ):
        """
        Инициализирует лимитер.

        Args:
            times (int): Количество разрешенных запросов.
            seconds (int): Временной интервал в секундах.
        """
        self.times = times
        self.seconds = seconds

    def __call__(self, func):
        """
        Декорирует маршрут, применяя к нему лимитер.

        Args:
            func: Функция маршрута, которую нужно декорировать.

        Returns:
            Callable: Обернутая функция с примененным лимитером.
        """

        @wraps(func)
        async def wrapper(*args, **kwargs):
            """
            Обертка для функции маршрута, которая применяет лимитер.

            Args:
                *args: Позиционные аргументы функции.
                **kwargs: Именованные аргументы функции.

            Returns:
                Результат выполнения оригинальной функции.

            Raises:
                ValueError: Если объект Request не найден.
                HTTPException: Если превышен лимит запросов.
            """
            # Извлекаем request из kwargs, если он есть
            request = kwargs.get("request")
            if not request:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break

            if not request:
                raise ValueError("Request object not found in args or kwargs")

            # Применяем RateLimiter к запросу
            rate_limiter = RateLimiter(times=self.times, seconds=self.seconds)
            try:
                # Создаем фиктивный объект Response
                response = Response()
                await rate_limiter(request, response)
            except HTTPException as e:
                raise HTTPException(
                    status_code=e.status_code,
                    detail=f"Rate limit exceeded: {e.detail}",
                )

            # Вызываем оригинальную функцию
            return await func(*args, **kwargs)

        return wrapper


# Создаем экземпляр лимитера с ограничением 5 запросов в 10 секунд
route_limiting = RouteLimiter()
