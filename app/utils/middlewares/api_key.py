from typing import List, Pattern

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.types import ASGIApp

from app.config.settings import settings


__all__ = ("APIKeyMiddleware",)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Middleware for API key validation in request headers"""

    def __init__(self, app: ASGIApp):
        import re

        super().__init__(app)
        self.compiled_patterns: List[Pattern] = [
            re.compile(self._convert_pattern(pattern))
            for pattern in settings.auth.routes_without_api_key
        ]

    @staticmethod
    def _convert_pattern(pattern: str) -> str:
        """Convert route pattern to regex pattern"""
        return f"^{pattern.replace('*', '.*')}$"

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if self._is_excluded_route(request.url.path):
            return await call_next(request)

        if (api_key := request.headers.get("X-API-Key")) is None:
            raise HTTPException(status_code=401, detail="API key required")

        if api_key != settings.auth.api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")

        return await call_next(request)

    def _is_excluded_route(self, path: str) -> bool:
        """Check if route is excluded from API key validation"""
        return any(pattern.match(path) for pattern in self.compiled_patterns)
