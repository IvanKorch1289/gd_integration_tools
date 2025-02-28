from asyncio import TimeoutError, wait_for

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)

from app.config.settings import settings
from app.utils.logging_service import app_logger


__all__ = ("TimeoutMiddleware",)


class TimeoutMiddleware(BaseHTTPMiddleware):
    """Middleware для ограничения времени обработки запросов.

    Обеспечивает:
    - Прерывание обработки запросов, превышающих заданное время
    - Логирование таймаутов
    - Возврат стандартизированного ответа при превышении времени
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """
        Обрабатывает запрос с ограничением по времени.

        Аргументы:
            request (Request): Входящий HTTP-запрос
            call_next (RequestResponseEndpoint): Следующий middleware/обработчик

        Возвращает:
            Response: HTTP-ответ или сообщение о таймауте

        Исключения:
            TimeoutError: Если время обработки превышено
        """
        try:
            # Ограничиваем время выполнения запроса
            return await wait_for(
                call_next(request), timeout=settings.secure.request_timeout
            )
        except TimeoutError:
            # Логируем факт таймаута
            app_logger.warning(
                f"Превышено время обработки запроса: {request.url}"
            )

            # Возвращаем стандартизированный ответ
            return JSONResponse(
                {"detail": "Превышено время обработки запроса"},
                status_code=408,
            )
