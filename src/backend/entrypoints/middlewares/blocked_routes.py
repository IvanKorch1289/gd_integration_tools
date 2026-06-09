import fnmatch

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from src.backend.core.state.runtime import blocked_routes

__all__ = ("BlockedRoutesMiddleware", "blocked_routes")


class BlockedRoutesMiddleware(BaseHTTPMiddleware):
    """Middleware для блокировки отключённых маршрутов.

    Проверяет, не совпадает ли запрашиваемый путь с одним из паттернов
    в ``blocked_routes`` (runtime_state). Поддерживает glob-шаблоны
    (``/api/v1/admin/*``, ``/health``). Если совпадение найдено — 403.
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
        path = request.url.path
        for pattern in blocked_routes:
            if fnmatch.fnmatch(path, pattern):
                raise HTTPException(status_code=403, detail="Route is disabled")
        return await call_next(request)
