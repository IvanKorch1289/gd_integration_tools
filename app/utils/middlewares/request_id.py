import uuid

from fastapi import Request, Response
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)


__all__ = ("RequestIDMiddleware",)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware for adding unique request ID to each request"""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or self._generate_id()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @staticmethod
    def _generate_id() -> str:
        return uuid.uuid4().hex
