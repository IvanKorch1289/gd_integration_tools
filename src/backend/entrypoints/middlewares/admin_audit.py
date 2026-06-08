"""Admin-audit middleware (S13 K1 W2).

Записывает в audit log каждый admin-action (PATCH/PUT/POST/DELETE на
``/api/v1/admin/*``, ``/tech/*``) с:

* ``actor.user_id`` / ``actor.principal`` — из ``request.state.auth_context``;
* ``actor.admin_roles`` — извлечённые через :func:`extract_admin_roles`;
* ``endpoint``, ``method``, ``status_code``;
* ``payload_hash`` — sha256 от body (для compliance, без хранения PII);
* ``correlation_id`` — для cross-trace связи;
* ``timestamp_utc``.

Не дублирует общий ``AuditLogMiddleware``: пишет в отдельный канал
(``audit_log.admin``) для compliance-фильтрации и долгого retention.
"""

from __future__ import annotations

import hashlib
import time as _time
from datetime import UTC, datetime

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from src.backend.core.auth.admin_roles import extract_admin_roles
from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("AdminAuditMiddleware",)

_admin_logger = get_logger("audit_log.admin")

_ADMIN_PATH_PREFIXES: tuple[str, ...] = ("/api/v1/admin/", "/tech/", "/api/v1/tech/")
_AUDITED_METHODS: frozenset[str] = frozenset({"PATCH", "PUT", "POST", "DELETE"})


def _is_admin_action(path: str, method: str) -> bool:
    """Определяет, надо ли аудитировать запрос."""
    if method not in _AUDITED_METHODS:
        return False
    return any(path.startswith(p) for p in _ADMIN_PATH_PREFIXES)


class AdminAuditMiddleware(BaseHTTPMiddleware):
    """Пишет admin-actions в ``audit_log.admin`` logger.

    Подключается в ``main.py`` после ``TenantMiddleware`` и
    ``AuthMethodHeaderMiddleware``, чтобы ``request.state.auth_context``
    уже был установлен.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        method = request.method
        if not _is_admin_action(path, method):
            return await call_next(request)

        start = _time.monotonic()
        body_bytes: bytes = b""
        cached = getattr(request.state, "body", None)
        if isinstance(cached, (bytes, bytearray)):
            body_bytes = bytes(cached)
        else:
            try:
                body_bytes = await request.body()
            except Exception:
                pass

        response = await call_next(request)
        duration_ms = (_time.monotonic() - start) * 1000

        auth_ctx = getattr(request.state, "auth_context", None)
        principal = (
            getattr(auth_ctx, "principal", "anonymous") if auth_ctx else "anonymous"
        )
        method_kind = getattr(auth_ctx, "method", None)
        admin_roles = sorted(r.value for r in extract_admin_roles(auth_ctx))
        payload_hash = hashlib.sha256(body_bytes).hexdigest() if body_bytes else ""
        correlation_id = getattr(request.state, "correlation_id", "") or ""

        _admin_logger.info(
            "admin_action",
            extra={
                "audit_admin": True,
                "actor_principal": principal,
                "actor_auth_method": getattr(
                    method_kind, "value", str(method_kind) if method_kind else "none"
                ),
                "actor_admin_roles": admin_roles,
                "endpoint": path,
                "method": method,
                "status_code": response.status_code,
                "payload_hash": payload_hash,
                "correlation_id": correlation_id,
                "duration_ms": round(duration_ms, 3),
                "timestamp_utc": datetime.now(UTC).isoformat(),
            },
        )
        return response
