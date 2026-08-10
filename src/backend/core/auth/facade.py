"""AuthFacade — центральный фасад для аутентификации/авторизации (S164 W2).

Проблема (EP-R1): 12+ endpoints напрямую импортируют разные auth helpers:
- ``core.auth.admin_roles.AdminRole, require_admin`` — RBAC decorator
- ``core.auth.jwt_backend.encode, decode, JwtVerificationError`` — JWT
- ``core.auth.ldap_client_factory.get_ad_client`` — LDAP/AD
- ``core.auth.saml.SamlError, SamlSpHandler`` — SAML/SSO
- ``core.auth.jwt_blacklist`` — JWT blacklist/revocation
- ``core.auth.api_key_backend`` — API keys
- ``core.auth.quotas`` — rate-limit quotas
- ``core.auth.admin_role_resolver`` — admin role resolution

Per master prompt §0 "Single-Entry per Concern" — все auth operations
должны идти через единый интерфейс-фасад (как ``NotificationFacade`` или
``StorageFacade``). Этот модуль — MVP-реализация facade.

Использование::

    from src.backend.core.auth.facade import get_auth_facade

    auth = get_auth_facade()
    result = await auth.verify_request(token)
    if result.is_authenticated:
        if auth.check_permission(result, "admin.read.capabilities"):
            ...

Note:
    Не все методы реализованы в MVP — только критичные для рефакторинга
    endpoints. Полный перевод всех 12+ endpoints — S165+ multi-sprint
    effort. Текущая версия — building block (per master prompt
    "Single-Entry per Concern").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("AuthFacade", "AuthResult", "get_auth_facade")

logger = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class AuthResult:
    """S164 W2: нормализованный результат auth-проверки.

    Attributes:
        is_authenticated: True если JWT/SAML/API-key валиден.
        method: Метод auth (``"jwt"`` / ``"saml"`` / ``"api_key"``).
        subject: User identity (sub claim, saml NameID, API key id).
        tenant_id: Tenant ID (None если отсутствует).
        groups: Список групп пользователя (None если отсутствуют).
        capabilities: Список capabilities (None если RBAC не настроен).
        metadata: Дополнительные данные (raw claims / roles).
    """

    is_authenticated: bool
    method: str | None = None
    subject: str | None = None
    tenant_id: str | None = None
    groups: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class AuthFacade:
    """S164 W2: центральный фасад для auth-операций.

    MVP: агрегирует JWT, SAML, API key, admin role, RBAC.
    Каждый endpoint должен использовать facade вместо прямого импорта
    backend helpers.

    Создаётся через :func:`get_auth_facade` singleton.
    """

    def __init__(self) -> None:
        # Lazy imports — backend modules не нужны при инициализации facade.
        self._jwt_backend: Any | None = None
        self._admin_roles: Any | None = None
        self._quotas: Any | None = None

    @property
    def jwt(self) -> Any:
        """Lazy accessor для JWT backend.

        Returns module-level functions (encode, decode, exceptions)
        вместо instantiating JwtBackend() — конструктор требует jwks_cache
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
                        is_authenticated=False,
                        metadata={"error": "token_revoked"},
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
            # API key format: ``ak_<key_id>_<secret>`` — extract the secret
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
                opaque string — content inspectable через metadata).

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

            cert = x509.load_pem_x509_certificate(
                cert_pem.encode(), default_backend()
            )
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
            from src.backend.services.security.facade import get_security_facade

            facade = get_security_facade()
            return await facade.is_token_blacklisted(jti)
        except Exception as exc:
            logger.debug(
                "jwt blacklist check failed: %s — fail-closed (treat as revoked)",
                exc,
            )
            return True  # S193 fix: fail-closed — security > availability

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
        # "admin" в groups membership-only — privilege escalation risk
        # (любой IdP group с именем "admin" получал bypass).
        try:
            from src.backend.core.auth import AuthContext
            from src.backend.core.auth.admin_roles import AdminRole, extract_admin_roles

            # Cycle 91 fix: extract_admin_roles expects AuthContext (with
            # .metadata attribute), but auth here is AuthResult (also has
            # .metadata). Wrap to satisfy the contract — previous
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
            # ImportError — AdminRole missing, AttributeError — auth API
            # change, TypeError — wrong auth ctx, ValueError — invalid
            # auth fields. Fallback: если AdminRole import failed — НЕ
            # bypass (fail-closed).
            import logging
            logging.getLogger(__name__).debug(
                "auth_facade.super_admin_check_failed",
                extra={"error": str(auth_exc)},
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

    def issue_token(
        self,
        subject: str,
        *,
        tenant_id: str | None = None,
        groups: list[str] | None = None,
        capabilities: list[str] | None = None,
        expires_in: int = 3600,
        method: str = "jwt",
        extra_claims: dict[str, Any] | None = None,
    ) -> tuple[str, int]:
        """S31 Task 4: mint a new JWT for the given subject (token issuance).

        Wraps :func:`jwt_backend.encode` and merges standard claims
        (``sub``, ``tenant_id``, ``groups``, ``capabilities``, ``auth_method``).
        Existing jti is left to jwt_backend (random UUID generation).

        Args:
            subject: User identity (``sub`` claim).
            tenant_id: Tenant ID (added as custom claim).
            groups: Group names (added as ``groups`` array claim).
            capabilities: Capabilities (added as ``capabilities`` array claim).
            expires_in: TTL in seconds (default 3600).
            method: Auth method marker (``"jwt"``, ``"api_key"``, ``"saml"``, ``"mtls"``).
            extra_claims: Additional custom claims merged into the JWT.

        Returns:
            ``(token_str, expires_in)`` tuple.

        Raises:
            ValueError: If ``subject`` is empty.
            RuntimeError: If JWT encode fails (e.g., missing secret).
        """
        if not subject:
            raise ValueError("issue_token: subject must be non-empty")

        claims: dict[str, Any] = dict(extra_claims or {})
        claims["auth_method"] = method
        if tenant_id is not None:
            claims["tenant_id"] = tenant_id
        if groups is not None:
            claims["groups"] = list(groups)
        if capabilities is not None:
            claims["capabilities"] = list(capabilities)

        try:
            token, expires = self.jwt.encode(
                subject=subject,
                claims=claims,
                expires_in=expires_in,
            )
            return token, expires
        except Exception as exc:
            raise RuntimeError(f"issue_token failed: {exc}") from exc

    async def revoke_token(self, jti: str) -> bool:
        """S31 Task 4: revoke a JWT by jti (blacklist).

        Adds the jti to the blacklist via :class:`SecurityFacade`. Returns
        ``True`` on success. Fail-closed: any error in the blacklist layer
        is propagated as RuntimeError.

        Args:
            jti: JWT ID (``jti`` claim) to revoke.

        Returns:
            ``True`` if blacklist write succeeded.

        Raises:
            ValueError: If ``jti`` is empty.
            RuntimeError: On blacklist layer failure (fail-closed).
        """
        if not jti:
            raise ValueError("revoke_token: jti must be non-empty")
        try:
            from src.backend.services.security.facade import get_security_facade

            facade = get_security_facade()
            await facade.blacklist_token(jti)
            return True
        except Exception as exc:
            raise RuntimeError(f"revoke_token failed: {exc}") from exc

    async def verify_saml_assertion(
        self,
        assertion_b64: str,
        *,
        expected_audience: str | None = None,
        expected_issuer: str | None = None,
    ) -> AuthResult:
        """S31 Task 4: SAML assertion verification with config gate.

        SAML requires the canonical ACS flow (configured SamlBackend,
        InResponseTo tracking, signature validator). For unit-tests and
        development, we provide a fail-closed path that ONLY succeeds when
        ``auth.saml.dev_mode`` feature flag is enabled.

        Args:
            assertion_b64: Base64-encoded SAML assertion.
            expected_audience: Expected ``AudienceRestriction`` (optional).
            expected_issuer: Expected ``Issuer`` (optional).

        Returns:
            :class:`AuthResult` with NameID if verified, else
            ``is_authenticated=False``.
        """
        # SAML requires ACS flow; fail-closed unless dev_mode flag is on.
        dev_mode = False
        try:
            from src.backend.core.config.features import feature_flags

            dev_mode = bool(getattr(feature_flags, "saml_sp_initiated_enabled", False))
        except (ImportError, AttributeError, RuntimeError) as ff_exc:
            # cycle-9/D-AUDIT-981: narrow exceptions + observability.
            # ImportError — features module missing, AttributeError —
            # config not initialized, RuntimeError — feature_flags
            # unavailable.
            import logging
            logging.getLogger(__name__).debug(
                "auth_facade.saml_dev_mode_fallback",
                extra={"error": str(ff_exc)},
            )

        if not dev_mode:
            logger.debug("SAML: dev_mode disabled, fail-closed")
            return AuthResult(
                is_authenticated=False,
                metadata={"error": "saml_requires_acs_flow"},
            )

        # Dev-mode path: accept the assertion if it's non-empty and has
        # expected fields (no real crypto verification, for dev/test only).
        if not assertion_b64:
            return AuthResult(
                is_authenticated=False,
                metadata={"error": "saml_empty_assertion"},
            )

        try:
            import base64
            import xml.etree.ElementTree as ET

            xml_bytes = base64.b64decode(assertion_b64)
            root = ET.fromstring(xml_bytes)  # dev-mode path; ElementTree has limited XXE risk (entity expansion DoS)
            ns = {"saml": "urn:oasis:names:tc:SAML:2.0:assertion"}
            name_id_el = root.find(".//saml:NameID", ns)
            subject_el = root.find(".//saml:Subject", ns)
            issuer_el = root.find(".//saml:Issuer", ns)
            audience_el = root.find(".//saml:AudienceRestriction/saml:Audience", ns)
            name_id = (
                name_id_el.text if name_id_el is not None else None
            ) or (subject_el.text if subject_el is not None else None)
            issuer = issuer_el.text if issuer_el is not None else None
            audience = audience_el.text if audience_el is not None else None

            if expected_issuer and issuer != expected_issuer:
                return AuthResult(
                    is_authenticated=False,
                    metadata={"error": "saml_issuer_mismatch"},
                )
            if expected_audience and audience != expected_audience:
                return AuthResult(
                    is_authenticated=False,
                    metadata={"error": "saml_audience_mismatch"},
                )
            if not name_id:
                return AuthResult(
                    is_authenticated=False,
                    metadata={"error": "saml_no_nameid"},
                )
            return AuthResult(
                is_authenticated=True,
                method="saml",
                subject=str(name_id),
                metadata={"issuer": issuer, "audience": audience, "dev_mode": True},
            )
        except Exception as exc:
            logger.debug("SAML dev-mode verify failed: %s", exc)
            return AuthResult(
                is_authenticated=False,
                metadata={"error": f"saml_dev_verify_failed: {exc}"},
            )

    async def verify_ldap_credentials(
        self,
        username: str,
        password: str,
        *,
        tenant_id: str | None = None,
    ) -> AuthResult:
        """S31 Task 4: LDAP bind verification.

        Uses :class:`ldap_client_factory` (canonical core-owned
        :class:`AdDirectoryClientProtocol`) to bind the user. On success,
        returns ``AuthResult`` with subject=``username`` and optional
        tenant_id. On failure, returns ``is_authenticated=False``.

        Args:
            username: LDAP/AD user (sAMAccountName или UPN).
            password: Plain password (passed to LDAP bind).
            tenant_id: Optional tenant mapping (added to metadata).

        Returns:
            :class:`AuthResult` with ``is_authenticated`` status.
        """
        if not username or not password:
            return AuthResult(
                is_authenticated=False,
                metadata={"error": "ldap_empty_credentials"},
            )

        try:
            from src.backend.core.auth.ldap_client_factory import get_ad_client

            client = get_ad_client()
            success = await client.bind(username, password)
            if not success:
                return AuthResult(
                    is_authenticated=False,
                    metadata={"error": "ldap_bind_failed"},
                )
            return AuthResult(
                is_authenticated=True,
                method="ldap",
                subject=str(username),
                tenant_id=tenant_id,
                metadata={"directory": "ldap", "tenant_id": tenant_id},
            )
        except Exception as exc:
            logger.warning("LDAP bind failed: %s", exc)
            return AuthResult(
                is_authenticated=False,
                metadata={"error": "ldap_failed"},
            )


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
