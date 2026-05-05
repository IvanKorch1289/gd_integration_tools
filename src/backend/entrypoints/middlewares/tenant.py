"""Tenant middleware — извлекает tenant_id из запроса и устанавливает в contextvar.

Wave 6.5a: ``set_correlation_context`` резолвится через DI provider
(``core.di.providers.get_correlation_context_setter_provider``), что
снимает entrypoints → infrastructure layer-violation.
"""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from src.backend.core.di.providers import get_correlation_context_setter_provider

__all__ = ("TenantMiddleware",)

_TENANT_HEADER = "X-Tenant-ID"


class TenantMiddleware(BaseHTTPMiddleware):
    """Извлекает tenant_id из заголовка/JWT и устанавливает в contextvar.

    Порядок приоритета:
    1. Header X-Tenant-ID
    2. JWT claim tenant_id (если auth middleware уже отработал)
    3. default tenant
    """

    def __init__(self, app: ASGIApp, default_tenant: str = "default") -> None:
        super().__init__(app)
        self._default = default_tenant

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        tenant_id = request.headers.get(_TENANT_HEADER)

        if not tenant_id:
            tenant_id = getattr(request.state, "tenant_id", None)

        if not tenant_id:
            tenant_id = self._default

        request.state.tenant_id = tenant_id
        get_correlation_context_setter_provider()(tenant_id=tenant_id)

        response = await call_next(request)
        response.headers["X-Tenant-ID"] = tenant_id
        return response
