"""Middleware, добавляющий header ``X-Auth-Method`` в response.

Полезно клиентам и observability: сразу видно, каким способом
запрос был аутентифицирован (api_key/jwt/express_jwt/...).

Метод считывается из ``request.state.auth`` (выставляется
``require_auth`` в ``auth_selector.py``). Если auth-контекст не
найден — header не добавляется.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

__all__ = ("AuthMethodHeaderMiddleware",)


class AuthMethodHeaderMiddleware(BaseHTTPMiddleware):
    """Прокидывает в response заголовок ``X-Auth-Method=<method>``."""

    def __init__(self, app: ASGIApp, header_name: str = "X-Auth-Method") -> None:
        super().__init__(app)
        self._header_name = header_name

    async def dispatch(self, request, call_next):  # type: ignore[override]
        response = await call_next(request)
        ctx = getattr(request.state, "auth", None)
        method = getattr(ctx, "method", None)
        if method is not None:
            value = getattr(method, "value", str(method))
            response.headers[self._header_name] = value
        return response
