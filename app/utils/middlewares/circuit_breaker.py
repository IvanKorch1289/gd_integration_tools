from aiocircuitbreaker import CircuitBreakerError, circuit
from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.config.settings import settings


__all__ = ("CircuitBreakerMiddleware",)


# Конфигурация Circuit Breaker
@circuit(
    failure_threshold=settings.secure.failure_threshold,  # Количество ошибок до размыкания цепи
    recovery_timeout=settings.secure.recovery_timeout,  # Время ожидания (в секундах) перед попыткой восстановления
    expected_exception=HTTPException,  # Тип исключения, считающегося ошибкой
)
async def protected_call_next(request: Request, call_next):
    """
    Защищенная функция, оборачивающая вызов следующего middleware с использованием Circuit Breaker.

    Аргументы:
        request (Request): Входящий HTTP-запрос.
        call_next (Callable): Следующий middleware или обработчик endpoint.

    Возвращает:
        Response: HTTP-ответ от следующего middleware или endpoint.

    Исключения:
        HTTPException: Если Circuit Breaker разомкнут или произошла ошибка.
    """
    return await call_next(request)


class CircuitBreakerMiddleware(BaseHTTPMiddleware):
    """
    Middleware для интеграции шаблона Circuit Breaker в FastAPI.

    Этот middleware оборачивает логику обработки запросов в Circuit Breaker,
    чтобы предотвращать каскадные сбои и повышать устойчивость системы.
    """

    async def dispatch(self, request: Request, call_next):
        """
        Обрабатывает запрос через Circuit Breaker.

        Аргументы:
            request (Request): Входящий HTTP-запрос.
            call_next (Callable): Следующий middleware или обработчик endpoint.

        Возвращает:
            Response: HTTP-ответ от следующего middleware или endpoint.

        Исключения:
            HTTPException: Если Circuit Breaker разомкнут или произошла ошибка.
        """
        try:
            # Оборачиваем вызов следующего middleware в Circuit Breaker
            response = await protected_call_next(request, call_next)
            return response
        except CircuitBreakerError:
            # Если Circuit Breaker разомкнут, возвращаем 503 Service Unavailable
            raise HTTPException(
                status_code=503,
                detail="Сервис временно недоступен из-за высокой частоты ошибок.",
            )
