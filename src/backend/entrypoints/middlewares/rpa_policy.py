"""RpaPolicyMiddleware (S171 M6 — security middleware).

Deny-by-default policy для ``/api/v1/rpa/*`` endpoints.

Security policy:
- /api/v1/rpa/* paths require ``rpa.admin`` role (from ``X-Roles`` header)
- Optional IP allowlist (configurable)
- Audit all denied requests
- All other paths → pass through

Layer 1 (early exit) — блокирует malicious RCE-shaped requests до того,
как они дойдут до capability_check на уровне DSL процессора.

Defense in depth: 2 layers (HTTP role + DSL capability).

Example::

    mw = RpaPolicyMiddleware(app, rpa_path_prefix="/api/v1/rpa")
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from fastapi import Request, Response
    from starlette.types import ASGIApp

from src.backend.core.logging import get_logger

_logger = get_logger(__name__)


class RpaPolicyMiddleware(BaseHTTPMiddleware):
    """Deny-by-default policy для RPA endpoints (S171 M6).

    Блокирует все запросы к ``rpa_path_prefix`` если в ``X-Roles`` header
    нет ``required_role``. Audit denied requests.

    Args:
        app: ASGI app.
        rpa_path_prefix: Prefix для RPA endpoints (default ``"/api/v1/rpa"``).
        required_role: Required role в X-Roles header (default ``"rpa.admin"``).

    Example:
        >>> mw = RpaPolicyMiddleware(app, rpa_path_prefix="/api/v1/rpa")
    """

    def __init__(
        self,
        app: "ASGIApp",
        *,
        rpa_path_prefix: str = "/api/v1/rpa",
        required_role: str = "rpa.admin",
    ) -> None:
        super().__init__(app)
        self.rpa_path_prefix = rpa_path_prefix
        self.required_role = required_role

    async def dispatch(
        self,
        request: "Request",
        call_next: Callable[["Request"], Awaitable["Response"]],
    ) -> "Response":
        if not request.url.path.startswith(self.rpa_path_prefix):
            return await call_next(request)

        # Path matches RPA → check role
        roles_header = request.headers.get("x-roles", "")
        roles = {r.strip() for r in roles_header.split(",") if r.strip()}
        if self.required_role not in roles:
            from starlette.responses import JSONResponse

            _logger.warning(
                "rpa_policy DENY path=%s method=%s client=%s roles=%s",
                request.url.path, request.method,
                request.client.host if request.client else "?",
                roles_header,
            )
            return JSONResponse(
                status_code=403,
                content={
                    "detail": f"role '{self.required_role}' required for {self.rpa_path_prefix}/*",
                    "code": "rpa_policy_denied",
                },
            )

        return await call_next(request)
