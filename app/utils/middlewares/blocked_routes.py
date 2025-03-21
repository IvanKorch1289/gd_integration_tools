from typing import Set

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware


__all__ = ("BlockedRoutesMiddleware", "blocked_routes")


blocked_routes: Set[str] = set()


# Middleware для блокировки
class BlockedRoutesMiddleware(BaseHTTPMiddleware):
    """Middleware для добавления уникального идентификатора запроса.

    Добавляет уникальный идентификатор (Request ID) к каждому входящему запросу:
    - Если идентификатор предоставлен в заголовках, использует его
    - Если идентификатор отсутствует, генерирует новый
    - Добавляет идентификатор в заголовки ответа
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
