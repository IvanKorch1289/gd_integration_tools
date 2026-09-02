# ruff: noqa: S314 -- false positive (controlled pattern)

"""AuthFacade -- центральный фасад для аутентификации/авторизации (S164 W2).

Проблема (EP-R1): 12+ endpoints напрямую импортируют разные auth helpers:
- ``core.auth.admin_roles.AdminRole, require_admin`` -- RBAC decorator
- ``core.auth.jwt_backend.encode, decode, JwtVerificationError`` -- JWT
- ``core.auth.ldap_client_factory.get_ad_client`` -- LDAP/AD
- ``core.auth.saml.SamlError, SamlSpHandler`` -- SAML/SSO
- ``core.auth.jwt_blacklist`` -- JWT blacklist/revocation
- ``core.auth.api_key_backend`` -- API keys
- ``core.auth.quotas`` -- rate-limit quotas
- ``core.auth.admin_role_resolver`` -- admin role resolution

Per master prompt §0 "Single-Entry per Concern" -- все auth operations
должны идти через единый интерфейс-фасад (как ``NotificationFacade`` или
``StorageFacade``). Этот модуль -- MVP-реализация facade.

Использование::

    from src.backend.core.auth.facade import get_auth_facade

    auth = get_auth_facade()
    result = await auth.verify_request(token)
    if result.is_authenticated:
        if auth.check_permission(result, "admin.read.capabilities"):
            ...

Note:
    Не все методы реализованы в MVP -- только критичные для рефакторинга
    endpoints. Полный перевод всех 12+ endpoints -- S165+ multi-sprint
    effort. Текущая версия -- building block (per master prompt
    "Single-Entry per Concern").

"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.backend.core.audit.facade._base import emit_audit_safe
from src.backend.core.auth.auth_result import AuthResult
from src.backend.core.auth.facade_token_mixin import AuthTokenMixin
from src.backend.core.auth.facade_verify_mixin import AuthVerifyMixin
from src.backend.core.logging import get_logger

__all__ = ("AuthFacade", "AuthResult", "get_auth_facade")

logger = get_logger(__name__)


# S61 M2-#1: AuthResult extracted в :mod:`auth_result` (data class only,
# no methods, no I/O). Re-exported ниже для backward-compat public API.


class AuthFacade(AuthTokenMixin, AuthVerifyMixin):
    """S164 W2: центральный фасад для auth-операций.

    MVP: агрегирует JWT, SAML, API key, admin role, RBAC.
    Каждый endpoint должен использовать facade вместо прямого импорта
    backend helpers.

    Создаётся через :func:`get_auth_facade` singleton.

    S63 M2-#1 split: composition root + AuthTokenMixin
    (issue_token + revoke_token в :mod:`facade_token_mixin`).
    Класс содержит 11 methods (verify_*, check_permission,
    get_tenant, properties).
    Tracking: docs/roadmap/PRODUCTION_READINESS.md M2-#1.

    S61 (predecessor): data class (:class:`AuthResult`) extracted в
    :mod:`auth_result`. Full AuthVerifyMixin split deferred S64+,
    ~280 LOC careful refactor с inter-method state dependencies
    (self._jwt_backend, self._admin_roles, self.quotas, self._is_blacklisted).
    """

    def __init__(self) -> None:
        # Lazy imports -- backend modules не нужны при инициализации facade.
        self._jwt_backend: Any | None = None
        self._admin_roles: Any | None = None
        self._quotas: Any | None = None

    @property
    def jwt(self) -> Any:
        """Lazy accessor для JWT backend.

        Returns module-level functions (encode, decode, exceptions)
        вместо instantiating JwtBackend() -- конструктор требует jwks_cache
        для asymmetric алгоритмов. Для facade достаточно module-level API.
        """
        if self._jwt_backend is None:
            from src.backend.core.auth import jwt_backend

            self._jwt_backend = jwt_backend
        return self._jwt_backend

    @property
    def admin_roles(self) -> Any:
        """Lazy accessor для admin role resolver."""
        if self._admin_roles is None:
            from src.backend.core.auth import admin_role_resolver

            self._admin_roles = admin_role_resolver
        return self._admin_roles

    @property
    def quotas(self) -> Any:
        """Lazy accessor для auth quotas."""
        if self._quotas is None:
            from src.backend.core.auth import quotas

            self._quotas = quotas
        return self._quotas

    async def verify_request(self, token: str, *, method: str = "jwt") -> AuthResult:
        """S164 W2: verify request token (JWT/SAML/API-key).

        Args:
            token: Encoded token (JWT) или API key.
            method: Auth method (``"jwt"`` / ``"api_key"`` / ``"saml"``).

        Returns:
            :class:`AuthResult` с decoded claims или ``is_authenticated=False``.

        """
        try:
            if method == "jwt":
                claims = self.jwt.decode(token)
                # S183 fix: blacklist check
                jti = claims.get("jti")
                if jti and await self._is_blacklisted(jti):
                    return AuthResult(
                        is_authenticated=False, metadata={"error": "token_revoked"}
                    )
                return AuthResult(
                    is_authenticated=True,
                    method="jwt",
                    subject=str(claims.get("sub", "")),
                    tenant_id=claims.get("tenant_id"),
                    groups=list(claims.get("groups", []) or []),
                    capabilities=list(claims.get("capabilities", []) or []),
                    metadata=dict(claims),
                )
            if method == "api_key":
                # S183 fix: API key verification через Argon2id backend.
                # Раньше был stub, всегда возвращал is_authenticated=False.
                return await self._verify_api_key(token)
            if method == "saml":
                # S183 fix: SAML assertion verification через SamlSpHandler
                return await self._verify_saml(token)
            if method == "mtls":
                # S183 fix: mTLS client cert verification
                return await self._verify_mtls(token)
        except Exception as exc:
            logger.warning("verify_request failed: %s", exc)
            # S48 W6 swarm audit (A1 Core #2): раньше silent 401 без следа
            # в audit. Атакующий получает silent 401 без observability.
            # Теперь эмитим audit.security.auth_verify_exception через
            # emit_audit_safe (Path A pattern -- never raises).
            emit_audit_safe(
                event="security.auth.verify_exception",
                action="verify_request",
                outcome="failure",
                severity="warning",
                extra={
                    "method": method,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:200],  # truncate to avoid log injection
                },
            )
            return AuthResult(is_authenticated=False, metadata={"error": "auth_failed"})
        return AuthResult(is_authenticated=False)

    async def _verify_api_key(self, api_key: str) -> AuthResult:
        """S183: API key verification через Argon2id backend.

        Args:
            api_key: Plain API key.

        Returns:
            AuthResult с subject/tenant_id если валидна.

        """
        try:
            from src.backend.core.auth.api_key_backend import APIKeyAuth

            api_key_auth = APIKeyAuth()
            # API key format: ``ak_<key_id>_<secret>`` -- extract the secret
            if not api_key.startswith("ak_"):
                return AuthResult(is_authenticated=False)

            parts = api_key.split("_", 2)
            if len(parts) != 3:
                return AuthResult(is_authenticated=False)

            # key_id (parts[0] + parts[1]) is embedded in the api_key string
            # already and is derived inside ``manager.validate_key`` from the
            # full token; not used here directly.
            secret = parts[2]

            # Fetch stored hash + metadata from API key registry
            # S202 audit fix: use DI provider instead of direct infra import
            from src.backend.core.di.providers.auth import get_api_key_manager_provider

            manager = get_api_key_manager_provider()
            # S202 audit fix: use ``validate_key`` (returns APIKeyInfo) instead
            # of non-existent ``.get(key_id)``. APIKeyInfo has ``key_hash``
            # attribute, not ``["hash"]``.
            info = await manager.validate_key(api_key)
            if info is None or not info.is_active:
                return AuthResult(is_authenticated=False)

            # Argon2id verify
            if not api_key_auth.verify(secret, info.key_hash):
                return AuthResult(is_authenticated=False)

            return AuthResult(
                is_authenticated=True,
                method="api_key",
                subject=info.client_id,
                tenant_id=None,
                groups=[],
                capabilities=[],
                metadata={"client_id": info.client_id, "key_version": info.version},
            )
        except Exception as exc:
            logger.warning("API key verify failed: %s", exc)
            return AuthResult(is_authenticated=False)

    async def _verify_saml(self, assertion: str) -> AuthResult:
        """S183: SAML assertion verification.

        Args:
            assertion: Base64-encoded SAML assertion (raw bytes или token
                opaque string -- content inspectable через metadata).

        Returns:
            AuthResult с NameID/subject.

        """
        # SAML verification requires the canonical ACS flow: configured
        # SamlBackend, InResponseTo and an injected signature validator.  A raw
        # assertion alone cannot satisfy that contract, so fail closed instead
        # of constructing SamlSpHandler with a non-existent legacy API.
        logger.debug("SAML assertion requires the configured ACS flow")
        # Include length-prefixed hash for observability WITHOUT leaking
        # the actual assertion bytes (security: never log SAML data).
        assertion_len = len(assertion) if assertion else 0
        return AuthResult(
            is_authenticated=False,
            metadata={
                "error": "saml_requires_acs_flow",
                "assertion_len": assertion_len,
            },
        )

    async def _verify_mtls(self, cert_pem: str) -> AuthResult:
        """S183: mTLS client cert identity extraction.

        SECURITY: certificate chain validation is performed by the TLS terminator
        (uvicorn/nginx). This method ONLY extracts identity (CN) from an
        already-validated client cert. It must not be called with untrusted input.

        Args:
            cert_pem: PEM-encoded client certificate (validated by TLS layer).

        Returns:
            AuthResult с CN/subject, or ``is_authenticated=False`` if cert is
            empty/invalid.

        """
        # SECURITY: certificate chain validation is performed by the TLS
        # terminator (uvicorn/nginx).
        if not cert_pem:
            return AuthResult(is_authenticated=False)
        try:
            from cryptography import x509
            from cryptography.hazmat.backends import default_backend

            cert = x509.load_pem_x509_certificate(cert_pem.encode(), default_backend())
            cn = None
            for attr in cert.subject:
                if attr.oid == x509.NameOID.COMMON_NAME:
                    cn = attr.value
                    break
            return AuthResult(
                is_authenticated=True,
                method="mtls",
                subject=cn or "",
                metadata={"fingerprint": cert.fingerprint(default_backend()).hex()},
            )
        except Exception as exc:
            logger.warning("mTLS identity extraction failed: %s", exc)
            return AuthResult(is_authenticated=False)

    async def _is_blacklisted(self, jti: str) -> bool:
        """S183: check JWT blacklist.

        Args:
            jti: JWT ID.

        Returns:
            True если blacklisted (fail-closed на ошибке Redis недоступности).

        S202 audit fix: использует :class:`SecurityFacade` singleton вместо
        создания нового ``RedisJwtBlacklist`` на каждый вызов
        (был performance hit + inconsistent state).

        """
        try:
            # S48 W10 swarm audit (A1 Core #5): inline import от services →
            # layer violation. Теперь canonical DI provider из core.
            from src.backend.core.di.providers.auth import get_security_facade_provider

            facade = get_security_facade_provider()
            return await facade.is_token_blacklisted(jti)
        except Exception as exc:
            logger.debug(
                "jwt blacklist check failed: %s -- fail-closed (treat as revoked)", exc
            )
            return True  # S193 fix: fail-closed -- security > availability

    def check_permission(self, auth: AuthResult, required_capability: str) -> bool:
        """S164 W2: check if authenticated subject has required capability.

        Args:
            auth: :class:`AuthResult` from :meth:`verify_request`.
            required_capability: Capability name (e.g. ``"admin.read.capabilities"``).

        Returns:
            ``True`` if subject has capability OR has SUPER_ADMIN role.

        """
        if not auth.is_authenticated:
            return False
        # S189+ fix: используем AdminRole enum вместо membership-only "admin" check.
        # "admin" в groups membership-only -- privilege escalation risk
        # (любой IdP group с именем "admin" получал bypass).
        try:
            from src.backend.core.auth import AuthContext
            from src.backend.core.auth.admin_roles import AdminRole, extract_admin_roles

            # Cycle 91 fix: extract_admin_roles expects AuthContext (with
            # .metadata attribute), but auth here is AuthResult (also has
            # .metadata). Wrap to satisfy the contract -- previous
            # ``extract_admin_roles(auth.metadata)`` passed raw dict which
            # raised AttributeError on ``dict.metadata`` → silently fell
            # through to ``return False`` → SUPER_ADMIN bypass NEVER worked.
            # Security-relevant: this fix restores admin bypass for real.
            auth_ctx = AuthContext(
                method=auth.method or "unknown",
                principal=auth.subject or "unknown",
                metadata=auth.metadata,
            )
            roles = extract_admin_roles(auth_ctx)
            if AdminRole.SUPER_ADMIN in roles:
                return True
        except (ImportError, AttributeError, TypeError, ValueError) as auth_exc:
            # cycle-9/D-AUDIT-980: narrow exceptions + observability.
            # ImportError -- AdminRole missing, AttributeError -- auth API
            # change, TypeError -- wrong auth ctx, ValueError -- invalid
            # auth fields. Fallback: если AdminRole import failed -- НЕ
            # bypass (fail-closed).
            import logging

            logging.getLogger(__name__).debug(
                "auth_facade.super_admin_check_failed", extra={"error": str(auth_exc)}
            )

        if required_capability in auth.capabilities:
            return True
        return False

    def get_tenant(self, auth: AuthResult) -> str | None:
        """S164 W2: extract tenant_id from AuthResult.

        Convenience wrapper around :func:`extract_tenant_id`.
        """
        from src.backend.core.auth.auth_context_helpers import extract_tenant_id

        return extract_tenant_id(auth)


# Singleton per pattern (NotificationFacade, StorageFacade, etc.).
_auth_facade: AuthFacade | None = None


def get_auth_facade() -> AuthFacade:
    """S164 W2: singleton accessor для AuthFacade.

    Returns:
        Module-level :class:`AuthFacade` instance.

    """
    global _auth_facade
    if _auth_facade is None:
        _auth_facade = AuthFacade()
    return _auth_facade
