from fastapi import Request, Response
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)


__all__ = ("RequestIDMiddleware",)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware для добавления уникального идентификатора запроса.

    Добавляет уникальный идентификатор (Request ID) к каждому входящему запросу:
    - Если идентификатор предоставлен в заголовках, использует его
    - Если идентификатор отсутствует, генерирует новый
    - Добавляет идентификатор в заголовки ответа
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """
        Обрабатывает входящий запрос, добавляя уникальный идентификатор.

        Аргументы:
            request (Request): Входящий HTTP-запрос
            call_next (RequestResponseEndpoint): Следующий middleware/обработчик

        Возвращает:
            Response: HTTP-ответ с добавленным идентификатором запроса
        """
        # Получаем или генерируем уникальный идентификатор запроса
        request_id = request.headers.get("X-Request-ID") or self._generate_id()

        # Сохраняем идентификатор в состоянии запроса
        request.state.request_id = request_id

        # Продолжаем обработку запроса
        response = await call_next(request)

        # Добавляем идентификатор в заголовки ответа
        response.headers["X-Request-ID"] = request_id

        return response

    @staticmethod
    def _generate_id() -> str:
        """
        Генерирует уникальный идентификатор запроса.

        Возвращает:
            str: Уникальный идентификатор в формате hex (32 символа)
        """
        from uuid import uuid4

        return uuid4().hex
