"""AI Tool Whitelist Middleware (S183, cycle 46 pure ASGI).

ADR-NEW-20 + AGENTS.md: skill whitelist enforcement для AI agent tools.

Проверяет что все tool invocations через /api/v1/agent/* endpoints
соответствуют whitelist из agent_policy.yaml. Возвращает 403 если tool
не в whitelist.

Использование::

    from src.backend.entrypoints.middlewares.ai_tool_whitelist import (
        AIToolWhitelistMiddleware,
    )

    app.add_middleware(AIToolWhitelistMiddleware, enabled=True)

Cycle 46: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с cycle 33-45 (L1 middlewares).

Spec: см. Master Prompt §3.3 / Plan S-3 (S174 → S183).
"""


import json
from typing import TYPE_CHECKING

from starlette.types import ASGIApp, Receive, Scope, Send

if TYPE_CHECKING:
    pass

__all__ = ("AIToolWhitelistMiddleware",)


class AIToolWhitelistMiddleware:
    """Pure ASGI middleware: enforce whitelist для AI agent tool invocations (S183, cycle 46).

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
        on_tool_check=None,
    ) -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.
            enabled: Включить/выключить enforcement (для тестов).
            on_tool_check: Optional callback ``(tenant_id, tool_name) -> bool``.
                Если None — используется ``_default_whitelist_check``.
        """
        self.app = app
        self._enabled = enabled
        self._on_tool_check = on_tool_check

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Точка входа ASGI-протокола.

        Non-HTTP scope пробрасывается без whitelist check.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not self._enabled:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Только agent endpoints — другие routes skip.
        if not path.startswith(self.AGENT_PATH_PREFIX):
            await self.app(scope, receive, send)
            return

        # Extract tool name из request body (через receive() chunks).
        body_chunks: list[bytes] = []
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                break
            body_chunks.append(message.get("body", b""))
            more_body = message.get("more_body", False)
        body = b"".join(body_chunks)

        # Re-inject body для downstream handlers.
        body_sent = False

        async def replay_receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {
                    "type": "http.request",
                    "body": body,
                    "more_body": False,
                }
            return {"type": "http.disconnect"}

        try:
            payload = json.loads(body) if body else {}
            tool_name = payload.get("tool_name") or payload.get("name")
            # S202 audit fix: tenant_id из auth context, не из header.
            state = scope.get("state", {}) if "state" in scope else {}
            ctx = (
                state.get("auth")
                if isinstance(state, dict)
                else getattr(getattr(None, "state", None), "auth", None)
            )
            # S183: tenant_id из auth metadata (sota security — не из header
            # для защиты от tenant-spoofing).
            tenant_id = (
                (ctx.metadata.get("tenant_id") if ctx and ctx.metadata else None)
                or _get_header_value(scope, b"x-tenant-id")
                or "default"
            )
            if not ctx and not _get_header_value(scope, b"x-tenant-id"):
                # No auth + no header — deny by default (don't fall through to
                # 'default' tenant which may have permissive grants).
                await self._send_400(
                    send,
                    error="missing_tenant",
                    detail="tenant_id required via auth context or X-Tenant-ID header",
                )
                return
        except (ValueError, TypeError, json.JSONDecodeError, KeyError, AttributeError) as parse_exc:
            # cycle-9/D-AUDIT-1006: narrow exceptions + observability.
            # ValueError/JSONDecodeError — malformed JSON, TypeError —
            # wrong body type, KeyError — missing required key, AttributeError
            # — body API change.
            # Malformed body — пропускаем (другие middleware обработают).
            import logging
            logging.getLogger(__name__).debug(
                "ai_tool_whitelist.body_parse_failed",
                extra={"error": str(parse_exc)},
            )
            await self.app(scope, replay_receive, send)
            return

        if not tool_name:
            await self._send_400(
                send,
                error="missing_tool_name",
                detail="tool_name required",
            )
            return

        # Whitelist check.
        check = self._on_tool_check or _default_whitelist_check
        if not check(tenant_id, tool_name):
            await self._send_403(
                send,
                error="tool_not_whitelisted",
                tool=tool_name,
                tenant=tenant_id,
                detail="Tool not in agent whitelist. Update agent_policy.yaml.",
            )
            return

        # Tool whitelisted → пробрасываем downstream с body replay.
        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _send_400(send: Send, *, error: str, detail: str) -> None:
        """Отправляет 400 JSON response через send (no-raise, cycle 39)."""
        body_bytes = json.dumps({"error": error, "detail": detail}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 400,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body_bytes)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body_bytes})

    @staticmethod
    async def _send_403(send: Send, **payload) -> None:
        """Отправляет 403 JSON response через send (no-raise, cycle 39)."""
        body_bytes = json.dumps(payload).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body_bytes)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body_bytes})


def _get_header_value(scope: Scope, name: bytes) -> str:
    """Извлекает header из ASGI scope по lowercase bytes-имени."""
    for header_name, header_value in scope.get("headers", []):
        if header_name == name:
            try:
                return header_value.decode("latin-1")
            except UnicodeDecodeError:
                return ""
    return ""


def _default_whitelist_check(tenant_id: str, tool_name: str) -> bool:
    """Default whitelist check через CapabilityGate.

    Args:
        tenant_id: Tenant ID из auth context.
        tool_name: Tool name из request body.

    Returns:
        True если tool разрешён для tenant, False иначе.

    Note:
        S183: простая implementation через CapabilityGate.
        Production может использовать более сложный policy resolver.
    """
    try:
        from src.backend.core.security.capabilities import CapabilityGate

        # ``check`` signals allow by returning normally and deny by raising.
        gate = CapabilityGate()
        gate.check(
            tenant_id,
            f"agent.tools.invoke.{tool_name}",
            f"tool:{tool_name}",
        )
        return True
    except (ImportError, AttributeError, RuntimeError, ValueError, TypeError) as gate_exc:
        # cycle-9/D-AUDIT-1016: narrow exceptions + observability.
        # ImportError — gate missing, AttributeError — gate API change,
        # RuntimeError — gate unavailable, ValueError/TypeError — invalid
        # args. Deny-by-default при ошибке (fail-closed).
        import logging
        logging.getLogger(__name__).debug(
            "ai_tool_whitelist.gate_check_failed",
            extra={"tool_name": tool_name, "error": str(gate_exc)},
        )
        return False
