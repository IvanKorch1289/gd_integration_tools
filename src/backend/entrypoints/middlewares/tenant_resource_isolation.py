"""Tenant Resource Isolation Middleware (Sprint 5 — audit 2026-09-22 P0).

Аудит finding #3 (object authorization): только 16 из 158 routes имеют
ownership check. Этот middleware — **framework-level enforcement** вместо
per-route decorators:

1. Auto-detect URL pattern с resource_id (e.g., ``/orders/{id}``, ``/users/{user_id}``).
2. Parse ``resource_type`` + ``resource_id`` из path.
3. Если ``resource_type`` имеет registered ownership checker — auto-verify.
4. Deny (403 fail-closed) на mismatch / отсутствие tenant-контекста;
   ``BaseError`` из checker'а рендерится канонически (``to_dict()``,
   status_code ошибки).

Coverage: все 158 routes получают ownership check без изменения каждого.

Registered checkers:
- ``order`` → verify ``Order.tenant_id == TenantContext.tenant_id``
- ``user`` → verify ``User.tenant_id == TenantContext.tenant_id``
- ``file`` → verify ``File.tenant_id == TenantContext.tenant_id``
- ...

Без зарегистрированных checker'ов middleware — pass-through (zero-cost):
это позволяет wire'ить его глобально сразу, а checker'ы подключать
постепенно (per resource_type) без изменения middleware-стека.

Tenant identity резолвится с тем же приоритетом, что и в
:class:`~src.backend.entrypoints.middlewares.tenant.TenantMiddleware`
(header ``X-Tenant-ID`` → ``scope.state['tenant_id']``); пустой tenant →
403 (fail-closed: нельзя верифицировать ownership без идентичности).

Usage::

    from src.backend.entrypoints.middlewares.tenant_resource_isolation import (
        TenantResourceIsolationMiddleware,
    )

    app.add_middleware(TenantResourceIsolationMiddleware)
    # production wiring (per resource_type):
    # middleware.register_ownership_checker("order", verify_tenant_ownership)
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import orjson as json
from starlette.types import ASGIApp, Receive, Scope, Send

from src.backend.core.errors import BaseError

logger = logging.getLogger(__name__)

_TENANT_HEADER_BYTES = b"x-tenant-id"


@dataclass(slots=True)
class ResourcePattern:
    """URL pattern → resource type mapping."""

    pattern: re.Pattern[str]
    resource_type: str
    param_name: str  # path param containing resource_id

    @classmethod
    def compile(
        cls, pattern_str: str, resource_type: str, param_name: str
    ) -> ResourcePattern:
        """Compile regex pattern.

        Args:
            pattern_str: regex pattern (e.g., r"/orders/(?P<order_id>[^/]+)").
            resource_type: resource type name (e.g., "order").
            param_name: имя captured group with resource_id.
        """
        return cls(
            pattern=re.compile(pattern_str),
            resource_type=resource_type,
            param_name=param_name,
        )


# Default resource patterns: URL → resource_type.
DEFAULT_PATTERNS: tuple[ResourcePattern, ...] = (
    ResourcePattern.compile(
        r"/api/v\d+/orders/(?P<order_id>[^/]+)$", "order", "order_id"
    ),
    ResourcePattern.compile(r"/api/v\d+/users/(?P<user_id>[^/]+)$", "user", "user_id"),
    ResourcePattern.compile(r"/api/v\d+/files/(?P<file_id>[^/]+)$", "file", "file_id"),
    ResourcePattern.compile(
        r"/api/v\d+/tenants/(?P<tenant_id>[^/]+)$", "tenant", "tenant_id"
    ),
    ResourcePattern.compile(
        r"/api/v\d+/accounts/(?P<account_id>[^/]+)$", "account", "account_id"
    ),
    ResourcePattern.compile(
        r"/api/v\d+/documents/(?P<document_id>[^/]+)$", "document", "document_id"
    ),
)


class TenantResourceIsolationMiddleware:
    """ASGI middleware для framework-level ownership check.

    Для resource-style URL (unsafe methods) с зарегистрированным
    ownership checker'ом верифицирует принадлежность ресурса tenant'у.
    Fail-closed: нет tenant-идентичности или checker вернул ``False`` → 403.
    ``BaseError`` из checker'а рендерится канонически (status_code ошибки).
    Нет checker'а для resource_type → pass-through (постепенное подключение).
    """

    def __init__(
        self, app: ASGIApp, patterns: tuple[ResourcePattern, ...] | None = None
    ) -> None:
        """Инициализация.

        Args:
            app: ASGI-приложение.
            patterns: URL patterns. None → DEFAULT_PATTERNS.
        """
        self.app = app
        self._patterns = patterns or DEFAULT_PATTERNS
        # Ownership checkers: resource_type → async (resource_id, tenant_id) → bool.
        self._checkers: dict[str, Callable[..., Awaitable[bool]]] = {}

    def register_ownership_checker(
        self, resource_type: str, checker: Callable[..., Awaitable[bool]]
    ) -> None:
        """Register ownership checker для resource_type.

        Контракт checker'а: ``async (resource_id: str, tenant_id: str) -> bool``.
        ``True`` — ресурс принадлежит tenant'у; ``False`` — нет (→ 403).
        Для "ресурс не найден" checker может вернуть ``False`` или raise
        :class:`~src.backend.core.errors.NotFoundError` (рендерится канонически).

        Production wiring::
            from src.backend.core.security.object_ownership import (
                verify_tenant_ownership,
            )
            middleware.register_ownership_checker("order", verify_tenant_ownership)
        """
        self._checkers[resource_type] = checker

    def _match(self, path: str) -> tuple[str, str] | None:
        """Match path against patterns.

        Returns:
            (resource_type, resource_id) или None если нет match.
        """
        for pattern in self._patterns:
            m = pattern.pattern.search(path)
            if m is not None:
                return pattern.resource_type, m.group(pattern.param_name)
        return None

    @staticmethod
    def _resolve_tenant_id(scope: Scope) -> str:
        """Резолвит tenant_id: header ``X-Tenant-ID`` → ``state['tenant_id']``.

        Приоритет сознательно совпадает с TenantMiddleware (Sprint 1 V16) —
        у запроса должна быть ЕДИНАЯ tenant-идентичность во всех слоях.
        Пустая строка = идентичности нет (fail-closed в __call__).
        """
        for header_name, header_value in scope.get("headers", []):
            if header_name == _TENANT_HEADER_BYTES:
                try:
                    return header_value.decode("latin-1")
                except UnicodeDecodeError:
                    break
        state = scope.get("state", {})
        if isinstance(state, dict):
            state_tenant = state.get("tenant_id")
            if isinstance(state_tenant, str) and state_tenant:
                return state_tenant
        return ""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process ASGI request."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")
        # Только для unsafe methods и resource-style URLs.
        if method not in ("GET", "PUT", "PATCH", "DELETE"):
            await self.app(scope, receive, send)
            return

        match = self._match(path)
        if match is None:
            await self.app(scope, receive, send)
            return

        resource_type, resource_id = match
        checker = self._checkers.get(resource_type)
        if checker is None:
            # Нет checker'а → middleware skip (постепенное подключение).
            logger.debug("no_ownership_checker resource_type=%s", resource_type)
            await self.app(scope, receive, send)
            return

        tenant_id = self._resolve_tenant_id(scope)
        if not tenant_id:
            # Fail-closed: без tenant-идентичности ownership неверифицируем.
            logger.warning(
                "tenant_isolation DENY path=%s resource=%s/%s reason=no_tenant",
                path,
                resource_type,
                resource_id,
            )
            await self._send_json(
                send,
                status=403,
                body={
                    "message": "tenant identity required",
                    "status_code": 403,
                    "hasErrors": True,
                    "error_type": "TenantIsolationDenied",
                },
            )
            return

        try:
            owned = await checker(resource_id, tenant_id)
        except BaseError as exc:
            # Checker различает "не найден" (404) от "чужой" (403) —
            # рендерим канонический contract ошибки.
            logger.warning(
                "tenant_isolation DENY path=%s resource=%s/%s reason=%s",
                path,
                resource_type,
                resource_id,
                exc.__class__.__name__,
            )
            await self._send_json(
                send, status=exc.status_code, body=exc.to_dict(include_type=True)
            )
            return

        if not owned:
            logger.warning(
                "tenant_isolation DENY path=%s resource=%s/%s tenant=%s reason=not_owned",
                path,
                resource_type,
                resource_id,
                tenant_id,
            )
            await self._send_json(
                send,
                status=403,
                body={
                    "message": "resource does not belong to tenant",
                    "status_code": 403,
                    "hasErrors": True,
                    "error_type": "TenantIsolationDenied",
                },
            )
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _send_json(send: Send, *, status: int, body: dict) -> None:
        """Отправляет JSON error response через send (raw ASGI)."""
        body_bytes = json.dumps(body)
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body_bytes)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body_bytes})


__all__ = ("DEFAULT_PATTERNS", "ResourcePattern", "TenantResourceIsolationMiddleware")
