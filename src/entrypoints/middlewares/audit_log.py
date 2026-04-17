"""Middleware для аудит-логирования.

Записывает: кто, когда, какой endpoint, метод, статус ответа,
время обработки. Работает через structlog/app_logger.
"""

from time import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

__all__ = ("AuditLogMiddleware",)


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Аудит-лог каждого HTTP-запроса."""

    def __init__(self, app: ASGIApp) -> None:
        from app.infrastructure.external_apis.logging_service import app_logger

        super().__init__(app)
        self.logger = app_logger

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time()
        response = await call_next(request)
        duration_ms = (time() - start) * 1000

        self.logger.info(
            "AUDIT | %s %s | status=%d | %.1fms | ip=%s | correlation=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request.client.host if request.client else "unknown",
            getattr(request.state, "correlation_id", "n/a"),
        )

        return response
