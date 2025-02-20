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
    """Middleware for request processing timeout"""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        try:
            return await wait_for(
                call_next(request), timeout=settings.auth.request_timeout
            )
        except TimeoutError:
            app_logger.warning(f"Request timeout: {request.url}")
            return JSONResponse(
                {"detail": "Request processing timeout"}, status_code=408
            )
