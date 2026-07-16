"""AuthorizationFacade — unified facade для authorization operations (S186 extended).

S183 I-7: Базовый facade с OPA/Casbin policy check.
S186: Расширен для unified authz через keys + tokens + cookies.

Теперь единый entry-point для ВСЕХ auth-операций:

**Unified Authorization API** (S186):
- :func:`authorize()` — unified auth check (capability + policy + tenant)
- :func:`check_token()` — JWT/API-key/cookie token authorization
- :func:`check_session()` — cookie-based session authorization
- :func:`check_api_key()` — API key authorization (with scopes)
- :func:`check_jwt()` — JWT authorization (with claims validation)
- :func:`check_principal()` — principal-based auth (unified)

**Policy API** (S183):
- :func:`check()` — policy-based authz check (Casbin/OPA/Permission)
- :func:`add_policy()` / :func:`remove_policy()` — policy management
- :func:`audit_decision()` — emit authz audit event

"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("AuthorizationFacade", "AuthDecision", "get_authorization_facade")

_logger = get_logger("services.authorization.facade")


@dataclass(slots=True, frozen=True)
class AuthDecision:
    """S186: Unified authorization decision.

    Attributes:
        allowed: True если authorized.
        method: Auth method (``"api_key"`` / ``"jwt"`` / ``"cookie"`` / ``"capability"`` / ``"policy"``).
        subject: Principal identity (user/service/api_key_id).
        tenant_id: Tenant ID из auth context.
        scopes: Granted scopes/permissions.
        reason: Decision reason (for deny/error).
        audit_id: Audit event ID для tracking.
    """

    allowed: bool
    method: str = "unknown"
    subject: str | None = None
    tenant_id: str | None = None
    scopes: tuple[str, ...] = ()
    reason: str = ""
    audit_id: str = ""


class AuthorizationFacade:
    """S186: Unified facade для authorization через keys, tokens, cookies.

    Wraps :class:`AuthorizationGateway` (OPA/Casbin/Permission) и
    """

    def __init__(self) -> None:
        """Инициализация facade."""
        self._gateway: Any | None = None
        self._auth_facade: Any | None = None

    @property
    def gateway(self) -> Any:
        """Lazy accessor для AuthorizationGateway."""
        if self._gateway is None:
            from src.backend.core.security.authorization_gateway import (
                AuthorizationGateway,
            )

            self._gateway = AuthorizationGateway
        return self._gateway

    @property
    def auth_facade(self) -> Any:
        if self._auth_facade is None:
            from src.backend.core.auth.facade import (
                get_auth_facade,
            )

            self._auth_facade = get_auth_facade()
        return self._auth_facade

    # ──────────────────── Unified Auth API (S186) ────────────────────

    async def authorize(
        self,
        *,
        token: str | None = None,
        cookie_session: str | None = None,
        required_capability: str | None = None,
        required_action: str | None = None,
        required_resource: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> AuthDecision:
        """S186: Unified authorization — single entry-point.

        Поддерживает все 3 метода auth:
        - JWT/API-key через ``token`` param
        - Cookie session через ``cookie_session`` param
        - Capability через ``required_capability``
        - Policy через ``required_action`` + ``required_resource``

        Args:
            token: Encoded token (JWT or API key).
            cookie_session: Session ID из cookie.
            required_capability: Capability name (e.g., ``"ds.read"``).
            required_action: Action для policy check (e.g., ``"read"``).
            required_resource: Resource для policy check.
            context: Дополнительный контекст.

        Returns:
            AuthDecision с allowed, method, scopes, etc.
        """
        # 1. Authentication phase
        auth_result = None
        method = "unknown"
        if token:
            # JWT or API key
            if token.startswith("ak_"):
                method = "api_key"
                auth_result = await self._check_api_key(token)
            else:
                method = "jwt"
                auth_result = await self._check_jwt(token)
        elif cookie_session:
            method = "cookie"
            auth_result = await self._check_cookie_session(cookie_session)

        if auth_result is not None and not auth_result.allowed:
            return auth_result

        # S202 audit fix: require authentication — anonymous requests denied.
        # Если ни token, ни cookie, ни capability не заданы — reject.
        if auth_result is None and not required_capability:
            return AuthDecision(
                allowed=False,
                method="anonymous",
                subject="",
                tenant_id=None,
                reason="no authentication provided",
            )

        # 2. Authorization phase (capability + policy)
        subject = auth_result.subject if auth_result else "_system"
        tenant_id = auth_result.tenant_id if auth_result else None

        if required_capability:
            cap_decision = await self._check_capability(
                subject, required_capability, tenant_id
            )
            if not cap_decision.allowed:
                return cap_decision

        if required_action and required_resource:
            policy_decision = self.check(
                subject, required_action, required_resource, context
            )
            if not policy_decision:
                return AuthDecision(
                    allowed=False,
                    method=method,
                    subject=subject,
                    tenant_id=tenant_id,
                    reason=f"policy denied: {required_action} on {required_resource}",
                )

        return AuthDecision(
            allowed=True,
            method=method,
            subject=subject,
            tenant_id=tenant_id,
        )

    async def check_token(
        self,
        token: str,
        *,
        method: str = "jwt",
        required_capability: str | None = None,
    ) -> AuthDecision:
        """S186: Token-based authorization (JWT or API key).

        Args:
            token: Encoded token.
            method: ``"jwt"`` или ``"api_key"``.
            required_capability: Optional capability check.

        Returns:
            AuthDecision.
        """
        if method == "api_key" or token.startswith("ak_"):
            return await self._check_api_key(token, required_capability)
        return await self._check_jwt(token, required_capability)

    async def check_session(
        self,
        session_id: str,
        *,
        required_capability: str | None = None,
    ) -> AuthDecision:
        """S186: Cookie session-based authorization.

        Args:
            session_id: Session ID из cookie (e.g., ``"sess_abc123"``).
            required_capability: Optional capability check.

        Returns:
            AuthDecision.
        """
        return await self._check_cookie_session(session_id, required_capability)

    async def check_api_key(
        self,
        api_key: str,
        *,
        required_scope: str | None = None,
    ) -> AuthDecision:
        """S186: API key authorization with optional scope check.

        Args:
            api_key: Plain API key (``ak_<key_id>_<secret>``).
            required_scope: Optional capability/scope required.

        Returns:
            AuthDecision.
        """
        return await self._check_api_key(api_key, required_scope)

    async def check_jwt(
        self,
        jwt_token: str,
        *,
        required_capability: str | None = None,
    ) -> AuthDecision:
        """S186: JWT authorization with optional capability check.

        Args:
            jwt_token: Encoded JWT.
            required_capability: Optional capability.

        Returns:
            AuthDecision.
        """
        return await self._check_jwt(jwt_token, required_capability)

    async def check_principal(
        self,
        principal: str,
        *,
        required_action: str,
        required_resource: str,
        context: dict[str, Any] | None = None,
    ) -> AuthDecision:
        """S186: Principal-based authorization (no token, already authenticated).

        Args:
            principal: User/service identity.
            required_action: Action.
            required_resource: Resource.
            context: Optional context.

        Returns:
            AuthDecision.
        """
        allowed = self.check(principal, required_action, required_resource, context)
        return AuthDecision(
            allowed=allowed,
            method="principal",
            subject=principal,
            reason="" if allowed else f"policy denied: {required_action}",
        )

    # ──────────────────── Implementation helpers ────────────────────

    async def _check_api_key(
        self,
        api_key: str,
        required_capability: str | None = None,
    ) -> AuthDecision:
        try:
            result = await self.auth_facade.verify_request(
                api_key, method="api_key"
            )

            if not result.is_authenticated:
                return AuthDecision(
                    allowed=False,
                    method="api_key",
                    reason="invalid api key",
                )

            if required_capability:
                cap_decision = await self._check_capability(
                    result.subject, required_capability, result.tenant_id
                )
                if not cap_decision.allowed:
                    return cap_decision

            return AuthDecision(
                allowed=True,
                method="api_key",
                subject=result.subject,
                tenant_id=result.tenant_id,
                scopes=tuple(result.capabilities),
            )
        except Exception as exc:
            _logger.debug("api_key check failed: %s", exc)
            return AuthDecision(
                allowed=False,
                method="api_key",
                reason=str(exc),
            )

    async def _check_jwt(
        self,
        jwt_token: str,
        required_capability: str | None = None,
    ) -> AuthDecision:
        try:
            result = await self.auth_facade.verify_request(
                jwt_token, method="jwt"
            )

            if not result.is_authenticated:
                return AuthDecision(
                    allowed=False,
                    method="jwt",
                    reason="invalid jwt",
                )

            if required_capability:
                cap_decision = await self._check_capability(
                    result.subject, required_capability, result.tenant_id
                )
                if not cap_decision.allowed:
                    return cap_decision

            return AuthDecision(
                allowed=True,
                method="jwt",
                subject=result.subject,
                tenant_id=result.tenant_id,
                scopes=tuple(result.capabilities),
            )
        except Exception as exc:
            _logger.debug("jwt check failed: %s", exc)
            return AuthDecision(
                allowed=False,
                method="jwt",
                reason=str(exc),
            )

    async def _check_cookie_session(
        self,
        session_id: str,
        required_capability: str | None = None,
    ) -> AuthDecision:
        """Cookie session verification (S202 audit fix).

        S186: stub возвращал всегда False. S202: реализует Redis-backed
        session lookup. Sessions хранятся как JSON под ключом
        ``session:{session_id}`` с TTL.

        Fail-closed: при отсутствии Redis или ошибке парсинга — отказ.
        """
        try:
            import json as _json

            from src.backend.infrastructure.clients.storage.redis import (
                get_redis_client,
            )

            redis_client = await get_redis_client().get_client("cache")
            raw = await redis_client.get(f"session:{session_id}")
            if raw is None:
                return AuthDecision(
                    allowed=False,
                    method="cookie",
                    reason="session not found or expired",
                )
            data = _json.loads(raw)
            subject = str(data.get("subject", ""))
            tenant_id = data.get("tenant_id")
            capabilities = list(data.get("capabilities", []) or [])

            if required_capability and required_capability not in capabilities:
                return AuthDecision(
                    allowed=False,
                    method="cookie",
                    subject=subject,
                    tenant_id=tenant_id,
                    reason=f"missing capability: {required_capability}",
                )

            return AuthDecision(
                allowed=True,
                method="cookie",
                subject=subject,
                tenant_id=tenant_id,
                scopes=tuple(capabilities),
            )
        except Exception as exc:
            _logger.debug("cookie session check failed: %s", exc)
            return AuthDecision(
                allowed=False,
                method="cookie",
                reason="session lookup failed",
            )

    async def _check_capability(
        self,
        subject: str,
        capability: str,
        tenant_id: str | None = None,
    ) -> AuthDecision:
        """Capability check через CapabilityFacade."""
        try:
            from src.backend.services.capabilities.facade import (
                CapabilityFacade,
                get_capability_facade,
            )

            cap_facade: CapabilityFacade = get_capability_facade()

            if tenant_id:
                allowed = cap_facade.check_tenant(
                    capability, tenant_id, principal_id=subject
                )
            else:
                allowed = cap_facade.check(subject, capability)

            return AuthDecision(
                allowed=allowed,
                method="capability",
                subject=subject,
                tenant_id=tenant_id,
                reason="" if allowed else f"capability denied: {capability}",
            )
        except Exception as exc:
            _logger.debug("capability check failed: %s", exc)
            return AuthDecision(
                allowed=False,
                method="capability",
                subject=subject,
                tenant_id=tenant_id,
                reason=str(exc),
            )

    # ──────────────────── Policy API (S183) ────────────────────

    def check(
        self,
        subject: str,
        action: str,
        resource: str,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """Authorization check (policy-based, Casbin/OPA)."""
        try:
            return self.gateway.check(subject, action, resource, context=context or {})
        except Exception as exc:
            _logger.debug(
                "authz check failed: subject=%s, action=%s, error=%s",
                subject,
                action,
                exc,
            )
            return False

    def add_policy(
        self,
        subject: str,
        action: str,
        resource: str,
        effect: str = "allow",
    ) -> bool:
        """Добавить policy rule."""
        try:
            self.gateway.add_policy(subject, action, resource, effect=effect)
            _logger.info(
                "policy added: %s/%s/%s/%s",
                subject,
                action,
                resource,
                effect,
            )
            return True
        except Exception as exc:
            _logger.warning("add_policy failed: %s", exc)
            return False

    def remove_policy(
        self,
        subject: str,
        action: str,
        resource: str,
    ) -> bool:
        """Удалить policy rule."""
        try:
            self.gateway.remove_policy(subject, action, resource)
            _logger.info(
                "policy removed: %s/%s/%s",
                subject,
                action,
                resource,
            )
            return True
        except Exception as exc:
            _logger.warning("remove_policy failed: %s", exc)
            return False

    async def audit_decision(
        self,
        subject: str,
        action: str,
        resource: str,
        decision: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Emit authorization decision audit event."""
        try:
            from src.backend.core.observability.logging_helpers import (
                log_audit_event_lite,
            )

            log_audit_event_lite(
                _logger,
                severity="info",
                event="authorization.decision",
                subject=subject,
                action=action,
                resource=resource,
                decision=decision,
                **(context or {}),
            )
        except Exception as exc:
            _logger.debug("audit_decision failed: %s", exc)


@lru_cache(maxsize=1)
def get_authorization_facade() -> AuthorizationFacade:
    """Lazy singleton глобального :class:`AuthorizationFacade`."""
    return AuthorizationFacade()
