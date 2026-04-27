from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.state.runtime import blocked_routes

__all__ = ("BlockedRoutesMiddleware", "blocked_routes")


# Middleware для блокировки
class BlockedRoutesMiddleware(BaseHTTPMiddleware):
    """Middleware для блокировки отключённых маршрутов.

    Проверяет, не находится ли запрашиваемый путь в множестве
    ``blocked_routes`` (runtime_state). Если да — возвращает 403.
    """

    async def dispatch(self, request: Request, call_next):
        """
        Обрабатывает входящий запрос к эндпоинту, проверяя его статус (заблокирован/разблокирован).

        Аргументы:
            request (Request): Входящий HTTP-запрос
            call_next (RequestResponseEndpoint): Следующий middleware/обработчик

        Возвращает:
            Response: HTTP-ответ
        """
        if request.url.path in blocked_routes:
            raise HTTPException(status_code=403, detail="Route is disabled")
        return await call_next(request)
