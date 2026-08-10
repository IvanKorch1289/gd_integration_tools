"""RpaPolicyMiddleware (S171 M6, cycle 40 pure ASGI) — security middleware.

Deny-by-default policy для ``/api/v1/rpa/*`` endpoints.

Security policy:
- /api/v1/rpa/* paths require ``rpa.admin`` role (из auth context)
- Audit all denied requests
- All other paths → pass through

Layer 1 (early exit) — блокирует malicious RCE-shaped requests до того,
как они дойдут до capability_check на уровне DSL процессора.

Defense in depth: 2 layers (HTTP role + DSL capability).

Cycle 40: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с cycle 33-39 (L1 middlewares).

Cycle 40 retrospective: auth context устанавливается в
``scope['state']['auth']`` UPSTREAM auth middleware (rpa_policy
идёт ПОСЛЕ auth в middleware chain). Поэтому resolution может
происходить в ``__call__`` напрямую — не нужен send-wrapper
pattern (как в cycle 37/38).

Cycle 40 critical: как и cycle 39 (BlockedRoutes), pure ASGI
НЕ МОЖЕТ return JSONResponse из __call__ — exception не
обрабатывается. Поэтому 403 отправляется напрямую через send.
"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Receive, Scope, Send

from src.backend.core.logging import get_logger

__all__ = ("RpaPolicyMiddleware",)

_logger = get_logger(__name__)


class RpaPolicyMiddleware:
    """Pure ASGI middleware: deny-by-default для RPA endpoints (S171 M6).

    Args:
        app: ASGI app.
        rpa_path_prefix: Prefix для RPA endpoints (default ``"/api/v1/rpa"``).
        required_role: Required role в auth context (default ``"rpa.admin"``).

    Example:
        >>> mw = RpaPolicyMiddleware(app, rpa_path_prefix="/api/v1/rpa")
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        rpa_path_prefix: str = "/api/v1/rpa",
        required_role: str = "rpa.admin",
    ) -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.
            rpa_path_prefix: Префикс RPA endpoints.
            required_role: Требуемая роль в auth context.
        """
        self.app = app
        self.rpa_path_prefix = rpa_path_prefix
        self.required_role = required_role

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Точка входа ASGI-протокола.

        Non-HTTP scope (``websocket`` / ``lifespan``) пробрасывается
        downstream-приложению без role-gate.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Path не RPA → пробрасываем downstream.
        if not path.startswith(self.rpa_path_prefix):
            await self.app(scope, receive, send)
            return

        # Path matches RPA → check role из auth context.
        # Auth middleware (outer) установил state['auth'] в pure ASGI scope.
        state = scope.get("state", {})
        auth = state.get("auth") if isinstance(state, dict) else None

        if auth is None:
            # No auth context → deny (fail-closed).
            _logger.warning(
                "rpa_policy DENY path=%s method=%s reason=no_auth_context",
                path,
                scope.get("method", "?"),
            )
            await self._send_403(
                send,
                body={
                    "detail": "authentication required for RPA endpoints",
                    "code": "rpa_policy_no_auth",
                },
            )
            return

        roles_attr = getattr(auth, "roles", []) or []
        # roles может быть set, list, tuple, или iterable.
        try:
            roles = set(roles_attr)
        except TypeError:
            roles = set()

        if self.required_role not in roles:
            # Get client host из scope (аналог request.client.host).
            client = scope.get("client")
            client_host = client[0] if client else "?"

            _logger.warning(
                "rpa_policy DENY path=%s method=%s client=%s roles=%s",
                path,
                scope.get("method", "?"),
                client_host,
                ",".join(sorted(roles)),
            )
            await self._send_403(
                send,
                body={
                    "detail": f"role '{self.required_role}' required for {self.rpa_path_prefix}/*",
                    "code": "rpa_policy_denied",
                },
            )
            return

        # Role есть → пробрасываем downstream.
        await self.app(scope, receive, send)

    @staticmethod
    async def _send_403(send: Send, *, body: dict) -> None:
        """Отправляет 403 JSON response через send."""
        body_bytes = json.dumps(body).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body_bytes)).encode("latin-1")),
                ],
            },
        )
        await send(
            {
                "type": "http.response.body",
                "body": body_bytes,
            },
        )
