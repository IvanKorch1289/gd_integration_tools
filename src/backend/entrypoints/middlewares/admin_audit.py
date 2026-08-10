"""Admin-audit middleware (S13 K1 W2, cycle 49 pure ASGI).

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

Cycle 49: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с cycle 33-48 (L1 middlewares).
"""

from __future__ import annotations

import time as _time
from datetime import UTC, datetime

from starlette.types import ASGIApp, Receive, Scope, Send

from src.backend.core.auth.admin_roles import extract_admin_roles
from src.backend.core.logging import get_logger

__all__ = ("AdminAuditMiddleware",)

_admin_logger = get_logger("audit_log.admin")

_ADMIN_PATH_PREFIXES: tuple[str, ...] = ("/api/v1/admin/", "/tech/", "/api/v1/tech/")
_AUDITED_METHODS: frozenset[str] = frozenset({"PATCH", "PUT", "POST", "DELETE"})


def _is_admin_action(path: str, method: str) -> bool:
    """Определяет, надо ли аудитировать запрос."""
    if method not in _AUDITED_METHODS:
        return False
    return any(path.startswith(p) for p in _ADMIN_PATH_PREFIXES)


class AdminAuditMiddleware:
    """Pure ASGI middleware: пишет admin-actions в ``audit_log.admin`` (cycle 49).

    Подключается после TenantMiddleware и AuthMethodHeaderMiddleware,
    чтобы ``request.state.auth_context`` уже был установлен.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.

        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Точка входа ASGI-протокола.

        Non-HTTP scope пробрасывается без audit.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")

        if not _is_admin_action(path, method):
            await self.app(scope, receive, send)
            return

        start = _time.monotonic()
        body_bytes: bytes = b""

        # IL-OBS1: cached body из RequestBodyCacheMiddleware имеет приоритет.
        state = scope.get("state", {}) if "state" in scope else {}
        cached = state.get("body") if isinstance(state, dict) else None
        if isinstance(cached, (bytes, bytearray)):
            body_bytes = bytes(cached)
        else:
            # Pure ASGI: collect body chunks через receive().
            body_chunks: list[bytes] = []
            more_body = True
            while more_body:
                message = await receive()
                if message["type"] == "http.disconnect":
                    break
                body_chunks.append(message.get("body", b""))
                more_body = message.get("more_body", False)
            body_bytes = b"".join(body_chunks)

        # Re-inject body для downstream handlers.
        body_sent = False

        async def replay_receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {
                    "type": "http.request",
                    "body": body_bytes,
                    "more_body": False,
                }
            return {"type": "http.disconnect"}

        # Capture response status через send_wrapper.
        response_status: dict[str, int] = {"status": 0}

        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                response_status["status"] = message.get("status", 0)
            await send(message)

        # Пробрасываем downstream с body replay.
        await self.app(scope, replay_receive, send_wrapper)

        duration_ms = (_time.monotonic() - start) * 1000

        # Extract audit data (cycle 49: from ASGI scope, not Request).
        auth_ctx = state.get("auth_context") if isinstance(state, dict) else None
        principal = (
            getattr(auth_ctx, "principal", "anonymous") if auth_ctx else "anonymous"
        )
        method_kind = getattr(auth_ctx, "method", None) if auth_ctx else None
        admin_roles = (
            sorted(r.value for r in extract_admin_roles(auth_ctx))
            if auth_ctx
            else []
        )
        from src.backend.entrypoints.middlewares._body_hash import payload_hash as _ph

        payload_hash = _ph(body_bytes)
        correlation_id = (
            state.get("correlation_id", "") if isinstance(state, dict) else ""
        )

        _admin_logger.info(
            "admin_action",
            extra={
                "audit_admin": True,
                "actor_principal": principal,
                "actor_auth_method": getattr(
                    method_kind, "value", str(method_kind) if method_kind else "none",
                ),
                "actor_admin_roles": admin_roles,
                "endpoint": path,
                "method": method,
                "status_code": response_status["status"],
                "payload_hash": payload_hash,
                "correlation_id": correlation_id,
                "duration_ms": round(duration_ms, 3),
                "timestamp_utc": datetime.now(UTC).isoformat(),
            },
        )
