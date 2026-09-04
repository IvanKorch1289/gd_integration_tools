"""AuthCoreMixin — verify + permission + tenant methods (S65 M2-#1 final split).

Extracted из :mod:`facade` (S164 W2 615 LOC god-object → split per
single-responsibility):
- :class:`AuthTokenMixin` (S63) -- issue_token + revoke_token
- :class:`AuthVerifyMixin` (S64) -- verify_saml_assertion + verify_ldap_credentials
- :class:`AuthCoreMixin` (S65, this file) -- 9 core methods (verify_request,
  _verify_api_key, _verify_saml, _verify_mtls, _is_blacklisted,
  check_permission, get_tenant, _enforce_quota)
- :class:`AuthFacade` (facade.py) -- composition root (init + 3 properties
  + get_auth_facade singleton)

All methods use ``self.jwt_backend``, ``self.admin_roles``, ``self.quotas``
properties (defined в :class:`AuthFacade`) и module-level ``logger``.

Re-exported из :mod:`facade` для backward-compat public API.
"""

from __future__ import annotations

from src.backend.core.audit.facade._base import emit_audit_safe
from src.backend.core.auth.auth_result import AuthResult

__all__ = ("AuthCoreMixin",)


class AuthCoreMixin:
    """Core auth methods mixin (M2-#1 final split).

    Methods:
    - verify_request: dispatcher для всех 4 auth methods (jwt/api_key/saml/mtls)
    - _verify_api_key: Argon2id API key validation
    - _verify_saml: SAML assertion (fail-closed)
    - _verify_mtls: mTLS cert identity extraction
    - _is_blacklisted: JWT jti blacklist check (fail-closed)
    - check_permission: SUPER_ADMIN role + capability check
    - get_tenant: extract tenant_id from AuthResult

    Methods access self.jwt_backend, self.admin_roles, self.quotas
    (properties, defined в :class:`AuthFacade`).
    MRO via mixin chain:
    ``AuthFacade(AuthTokenMixin, AuthVerifyMixin, AuthCoreMixin)``.
    """

    __slots__ = ()

    async def verify_request(self, token: str, *, method: str = "jwt") -> AuthResult:
        """S164 W2: verify request token (JWT/SAML/API-key).

        Args:
            token: Encoded token (JWT) или API key.
            method: Auth method (``"jwt"`` / ``"api_key"`` / ``"saml"``).

        Returns:
            :class:`AuthResult` с decoded claims или ``is_authenticated=False``.

        """
        from src.backend.core.auth.facade import logger

        try:
            if method == "jwt":
                claims = self.jwt.decode(token)
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
                return await self._verify_api_key(token)
            if method == "saml":
                return await self._verify_saml(token)
            if method == "mtls":
                return await self._verify_mtls(token)
        except Exception as exc:
            logger.warning("verify_request failed: %s", exc)
            emit_audit_safe(
                event="security.auth.verify_exception",
                action="verify_request",
                outcome="failure",
                severity="warning",
                extra={
                    "method": method,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:200],
                },
            )
            return AuthResult(is_authenticated=False, metadata={"error": "auth_failed"})
        return AuthResult(is_authenticated=False)

    async def _verify_api_key(self, api_key: str) -> AuthResult:
        """S183: API key verification через Argon2id backend."""
        from src.backend.core.auth.facade import logger

        try:
            from src.backend.core.auth.api_key_backend import APIKeyAuth

            api_key_auth = APIKeyAuth()
            if not api_key.startswith("ak_"):
                return AuthResult(is_authenticated=False)

            parts = api_key.split("_", 2)
            if len(parts) != 3:
                return AuthResult(is_authenticated=False)

            secret = parts[2]
            from src.backend.core.di.providers.auth import get_api_key_manager_provider

            manager = get_api_key_manager_provider()
            info = await manager.validate_key(api_key)
            if info is None or not info.is_active:
                return AuthResult(is_authenticated=False)

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
        """S183: SAML assertion verification (fail-closed ACS flow)."""
        from src.backend.core.auth.facade import logger

        logger.debug("SAML assertion requires the configured ACS flow")
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

        SECURITY: certificate chain validation is performed by the TLS
        terminator. This method ONLY extracts identity (CN).
        """
        from src.backend.core.auth.facade import logger

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
        """S183: check JWT blacklist (fail-closed)."""
        from src.backend.core.auth.facade import logger

        try:
            from src.backend.core.di.providers.auth import get_security_facade_provider

            facade = get_security_facade_provider()
            return await facade.is_token_blacklisted(jti)
        except Exception as exc:
            logger.debug(
                "jwt blacklist check failed: %s -- fail-closed", exc
            )
            return True

    def check_permission(self, auth: AuthResult, required_capability: str) -> bool:
        """S164 W2: check capability + SUPER_ADMIN role."""
        if not auth.is_authenticated:
            return False
        try:
            from src.backend.core.auth import AuthContext
            from src.backend.core.auth.admin_roles import AdminRole, extract_admin_roles

            auth_ctx = AuthContext(
                method=auth.method or "unknown",
                principal=auth.subject or "unknown",
                metadata=auth.metadata,
            )
            roles = extract_admin_roles(auth_ctx)
            if AdminRole.SUPER_ADMIN in roles:
                return True
        except (ImportError, AttributeError, TypeError, ValueError) as auth_exc:
            import logging

            logging.getLogger(__name__).debug(
                "auth_facade.super_admin_check_failed", extra={"error": str(auth_exc)}
            )

        if required_capability in auth.capabilities:
            return True
        return False

    def get_tenant(self, auth: AuthResult) -> str | None:
        """S164 W2: extract tenant_id from AuthResult."""
        from src.backend.core.auth.auth_context_helpers import extract_tenant_id

        return extract_tenant_id(auth)
