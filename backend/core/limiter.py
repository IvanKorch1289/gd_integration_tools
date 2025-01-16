from functools import wraps

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter

from backend.core.settings import settings


app = FastAPI()


# Функция для инициализации лимитера
async def init_limiter():
    """
    Инициализирует Redis и FastAPILimiter.
    """
    redis_connection = redis.from_url(
        "redis://localhost:6379", encoding="utf-8", decode_responses=True
    )
    await FastAPILimiter.init(redis_connection)


# Класс для лимитирования маршрутов
class RouteLimiter:
    def __init__(
        self,
        times: int = settings.app_rate_limit,
        seconds: int = settings.app_rate_time_measure_seconds,
    ):
        """
        Инициализация лимитера.

        :param times: Количество разрешенных запросов.
        :param seconds: Временной интервал в секундах.
        """
        self.times = times
        self.seconds = seconds

    def __call__(self, func):
        """
        Декорирует маршрут, применяя к нему лимитер.

        :param func: Функция маршрута, которую нужно декорировать.
        :return: Обернутая функция с примененным лимитером.
        """

        @wraps(func)
        async def wrapper(*args, **kwargs):
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
                raise e

            # Вызываем оригинальную функцию
            return await func(*args, **kwargs)

        return wrapper


# Создаем экземпляр лимитера с ограничением 5 запросов в 10 секунд
route_limiter = RouteLimiter()
