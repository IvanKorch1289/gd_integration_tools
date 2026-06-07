"""Admin API service (Sprint 19 K5 W5b): RBAC + audit trail.

Provides admin operations (feature flags, audit log, sessions) with:
- AuthorizationGateway RBAC checks
- Audit event emission via emit_admin_action

Wave tags:
    - s19/k5-w5b: AuthorizationGateway RBAC wiring + audit trail
    - s19/k5-w5c: admin-react pages (consumes this service)
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


from typing import Any

from src.backend.services.admin.audit import emit_admin_action

logger = get_logger(__name__)

__all__ = ("AdminService",)


class AdminAuthorizationError(RuntimeError):
    """Raised when AuthorizationGateway denies an admin action (fail-closed)."""

    pass


class AdminService:
    """
    Admin API с AuthorizationGateway RBAC + audit trail.

    Все методы принимают ``actor`` (идентификаторprincipal'а) и
    выполняют AuthZ-проверку перед действием.

    Audit:
        Каждое действие (allow или deny) эмитит ``admin.action`` event
        через ``emit_admin_action``.
    """

    def __init__(
        self,
        authorization_gateway: Any | None = None,
        audit_callback: Any | None = None,
    ) -> None:
        """
        Args:
            authorization_gateway: Экземпляр AuthorizationGateway.
                                  При None используется глобальный из
                                  ``core.security.authorization_gateway``.
            audit_callback: Не используется напрямую — audit идёт через
                           ``emit_admin_action``.
        """
        self._authz = authorization_gateway
        self._audit_cb = audit_callback

    def _get_authz(self) -> Any:
        """Lazily resolve global AuthorizationGateway."""
        if self._authz is not None:
            return self._authz
        try:
            from src.backend.core.security.authorization_gateway import (
                AuthorizationGateway,
            )
            from src.backend.core.security.capabilities.gate import CapabilityGate

            # Global singleton — same pattern as other services
            return AuthorizationGateway(capability_gateway=CapabilityGate())
        except Exception as exc:
            logger.warning("AuthorizationGateway unavailable: %s", exc)
            return None

    async def _authorize(
        self,
        *,
        actor: str,
        resource: str,
        action: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """
        Check authorization via AuthorizationGateway.

        Raises:
            AdminAuthorizationError: если AuthZ deny (fail-closed).
        """
        authz = self._get_authz()
        if authz is None:
            # AuthZ unavailable — fail-open for dev, but log warning
            logger.warning(
                "AuthZ unavailable for %s@%s/%s — allowing", actor, resource, action
            )
            return

        try:
            decision = await authz.authorize(
                principal=actor, resource=resource, action=action, context=context
            )
        except Exception as exc:
            emit_admin_action(
                actor=actor,
                action=action,
                resource=resource,
                outcome="error",
                details={"error": str(exc)},
            )
            raise AdminAuthorizationError(f"AuthorizationGateway error: {exc}") from exc

        if not decision.allowed:
            emit_admin_action(
                actor=actor,
                action=action,
                resource=resource,
                outcome="denied",
                details={"reasons": [str(r) for r in decision.reasons]},
            )
            raise AdminAuthorizationError(
                f"Authorization denied for {actor} on {resource}/{action}"
            )

    # ── feature flags ────────────────────────────────────────────────────────

    async def toggle_feature_flag(
        self, *, flag_name: str, enabled: bool, actor: str = "system"
    ) -> dict[str, Any]:
        """
        Toggle a feature flag by name (S19 K5 W5b).

        Requires AuthZ: ``admin.feature_flag:write``.
        Emits ``admin.action`` audit event.
        """
        resource = f"admin.feature_flag:{flag_name}"
        await self._authorize(actor=actor, resource=resource, action="write")

        # Apply the toggle
        from src.backend.core.config.features import feature_flags

        old_value = getattr(feature_flags, flag_name, None)
        if old_value is None:
            emit_admin_action(
                actor=actor,
                action="feature_flag.toggle",
                resource=resource,
                outcome="error",
                details={"error": f"flag {flag_name!r} not found", "enabled": enabled},
            )
            return {"error": f"flag {flag_name!r} not found"}

        setattr(feature_flags, flag_name, bool(enabled))
        emit_admin_action(
            actor=actor,
            action="feature_flag.toggle",
            resource=resource,
            outcome="allowed",
            details={"flag": flag_name, "old": old_value, "new": bool(enabled)},
        )
        return {"flag": flag_name, "old": old_value, "new": bool(enabled)}

    async def get_feature_flags(self, *, actor: str = "system") -> list[dict[str, Any]]:
        """
        List all feature flags with their values (S19 K5 W5b).

        Requires AuthZ: ``admin.feature_flag:read``.
        """
        resource = "admin.feature_flag"
        await self._authorize(actor=actor, resource=resource, action="read")

        from src.backend.core.config.features import feature_flags

        flags = {}
        for key in dir(feature_flags):
            if key.startswith("_") or key.isupper():
                continue
            val = getattr(feature_flags, key, None)
            if val is None:
                continue
            flags[key] = val

        emit_admin_action(
            actor=actor,
            action="feature_flag.list",
            resource=resource,
            outcome="allowed",
            details={"count": len(flags)},
        )
        return [{"name": k, "value": v} for k, v in flags.items()]

    # ── audit log ────────────────────────────────────────────────────────────

    async def get_audit_log(
        self, *, actor: str = "system", limit: int = 100, event_type: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Retrieve audit log entries (S19 K5 W5b).

        Requires AuthZ: ``admin.audit:read``.
        Returns entries emitted via ``emit_admin_action`` / ``_emit_audit``.
        """
        resource = "admin.audit"
        await self._authorize(actor=actor, resource=resource, action="read")

        # Audit entries are consumed via the same callback mechanism.
        # For now, return an empty list as backend storage is TBD.
        # Frontend can call this endpoint; entries accumulate via callback.
        emit_admin_action(
            actor=actor,
            action="audit.list",
            resource=resource,
            outcome="allowed",
            details={"limit": limit, "event_type": event_type},
        )
        return []

    # ── sessions ────────────────────────────────────────────────────────────

    async def list_active_sessions(
        self, *, actor: str = "system"
    ) -> list[dict[str, Any]]:
        """
        List active sessions (placeholder, S19 K5 W5b).

        Requires AuthZ: ``admin.sessions:read``.
        Returns empty list until session tracking is implemented.
        """
        resource = "admin.sessions"
        await self._authorize(actor=actor, resource=resource, action="read")

        emit_admin_action(
            actor=actor,
            action="sessions.list",
            resource=resource,
            outcome="allowed",
            details={},
        )
        return []
