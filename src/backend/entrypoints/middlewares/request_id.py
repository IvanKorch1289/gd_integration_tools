"""Middleware для Request ID и Correlation ID.

Обеспечивает сквозную трассировку запросов через все
протоколы и компоненты системы.

- **X-Request-ID**: уникальный идентификатор конкретного
  HTTP-запроса (генерируется на входе, если не передан).
- **X-Correlation-ID**: идентификатор цепочки вызовов
  (пробрасывается между сервисами, генерируется если
  отсутствует).
"""

from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

__all__ = ("RequestIDMiddleware",)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware для Request ID и Correlation ID.

    Добавляет оба идентификатора в ``request.state``
    и в заголовки ответа. Это позволяет:
    - Логировать запросы с привязкой к correlation_id.
    - Передавать correlation_id в DSL Exchange, gRPC
      metadata, очереди и другие протоколы.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Обрабатывает запрос, добавляя Request ID и Correlation ID.

        Args:
            request: Входящий HTTP-запрос.
            call_next: Следующий middleware/обработчик.

        Returns:
            HTTP-ответ с добавленными идентификаторами.
        """
        request_id = request.headers.get("X-Request-ID") or self._generate_id()
        correlation_id = request.headers.get("X-Correlation-ID") or self._generate_id()

        request.state.request_id = request_id
        request.state.correlation_id = correlation_id

        response = await call_next(request)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = correlation_id

        return response

    @staticmethod
    def _generate_id() -> str:
        """Генерирует уникальный идентификатор.

        Returns:
            UUID в формате hex (32 символа).
        """
        return uuid4().hex
