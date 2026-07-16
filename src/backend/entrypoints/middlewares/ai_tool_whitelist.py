"""AI Tool Whitelist Middleware (S183 — S-3 fix).

ADR-NEW-20 + AGENTS.md: skill whitelist enforcement для AI agent tools.

Проверяет что все tool invocations через /api/v1/agent/* endpoints
соответствуют whitelist из agent_policy.yaml. Возвращает 403 если tool
не в whitelist.

Использование::

    from src.backend.entrypoints.middlewares.ai_tool_whitelist import (
        AIToolWhitelistMiddleware,
    )

    app.add_middleware(AIToolWhitelistMiddleware, enabled=True)

Spec: см. Master Prompt §3.3 / Plan S-3 (S174 → S183).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

if TYPE_CHECKING:
    pass

__all__ = ("AIToolWhitelistMiddleware",)


class AIToolWhitelistMiddleware(BaseHTTPMiddleware):
    """Enforce whitelist для AI agent tool invocations (S183).

    Ловит все запросы к ``/api/v1/agent/tools/invoke`` и проверяет
    что requested tool находится в whitelist (per-tenant).

    Defaults:
    - Только path ``/api/v1/agent/tools/invoke`` проверяется (другие routes skip)
    - Whitelist читается из agent policy (lazy load)
    - Если whitelist пустой — все tools denied (deny-by-default)
    - Capability check требует ``agent.tools.invoke``
    """

    AGENT_PATH_PREFIX = "/api/v1/agent/tools/invoke"

    def __init__(
        self,
        app: ASGIApp,
        *,
        enabled: bool = True,
        on_tool_check: Callable[[str, str], bool] | None = None,
    ) -> None:
        """Инициализация middleware.

        Args:
            app: ASGI-приложение.
            enabled: Включить/выключить enforcement (для тестов).
            on_tool_check: Optional callback ``(tenant_id, tool_name) -> bool``.
                Если None — используется ``get_default_whitelist_check()``.
        """
        super().__init__(app)
        self._enabled = enabled
        self._on_tool_check = on_tool_check

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Process request с whitelist enforcement."""
        if not self._enabled:
            return await call_next(request)

        # Только agent endpoints
        if not request.url.path.startswith(self.AGENT_PATH_PREFIX):
            return await call_next(request)

        # Extract tool name из request body
        try:
            body = await request.body()
            import json

            payload = json.loads(body) if body else {}
            tool_name = payload.get("tool_name") or payload.get("name")
            tenant_id = request.headers.get("X-Tenant-ID", "default")
        except Exception:
            # Malformed body — пропускаем (другие middleware обработают)
            return await call_next(request)

        if not tool_name:
            return JSONResponse(
                {"error": "missing_tool_name", "detail": "tool_name required"},
                status_code=400,
            )

        # Whitelist check
        check = self._on_tool_check or _default_whitelist_check
        if not check(tenant_id, tool_name):
            return JSONResponse(
                {
                    "error": "tool_not_whitelisted",
                    "tool": tool_name,
                    "tenant": tenant_id,
                    "detail": "Tool not in agent whitelist. Update agent_policy.yaml.",
                },
                status_code=403,
            )

        return await call_next(request)


def _default_whitelist_check(tenant_id: str, tool_name: str) -> bool:
    """Default whitelist check через CapabilityGate.

    Args:
        tenant_id: Tenant ID из X-Tenant-ID header.
        tool_name: Tool name из request body.

    Returns:
        True если tool разрешён для tenant, False иначе.

    Note:
        S183: простая implementation через CapabilityGate.
        Production может использовать более сложный policy resolver.
    """
    try:
        from src.backend.core.security.capabilities import CapabilityGate

        # Проверяем capability pattern: ``agent.tools.invoke.<tool_name>``
        return CapabilityGate.check(
            tenant_id,
            f"agent.tools.invoke.{tool_name}",
            f"tool:{tool_name}",
        )
    except Exception:
        # Deny-by-default при ошибке
        return False
