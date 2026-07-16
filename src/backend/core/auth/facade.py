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
            logger.debug("verify_request failed: %s", exc)
            return AuthResult(is_authenticated=False, metadata={"error": str(exc)})
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
            # API key format: ``ak_<key_id>_<secret>`` — extract key_id
            if not api_key.startswith("ak_"):
                return AuthResult(is_authenticated=False)

            parts = api_key.split("_", 2)
            if len(parts) != 3:
                return AuthResult(is_authenticated=False)

            key_id = f"{parts[0]}_{parts[1]}"
            secret = parts[2]

            # Fetch stored hash + metadata from API key registry
            # S202 audit fix: use DI provider instead of direct infra import
            from src.backend.core.di.providers.auth import (
                get_api_key_manager_provider,
            )

            manager = get_api_key_manager_provider()
            stored = await manager.get(key_id)
            if stored is None:
                return AuthResult(is_authenticated=False)

            # Argon2id verify
            if not api_key_auth.verify(secret, stored["hash"]):
                return AuthResult(is_authenticated=False)

            return AuthResult(
                is_authenticated=True,
                method="api_key",
                subject=stored.get("subject", key_id),
                tenant_id=stored.get("tenant_id"),
                groups=stored.get("groups", []),
                capabilities=stored.get("capabilities", []),
                metadata={"key_id": key_id},
            )
        except Exception as exc:
            logger.debug("API key verify failed: %s", exc)
            return AuthResult(is_authenticated=False)

    async def _verify_saml(self, assertion: str) -> AuthResult:
        """S183: SAML assertion verification.

        Args:
            assertion: Base64-encoded SAML assertion.

        Returns:
            AuthResult с NameID/subject.
        """
        try:
            from src.backend.core.auth.saml import SamlSpHandler

            handler = SamlSpHandler()
            claims = handler.verify_assertion(assertion)
            return AuthResult(
                is_authenticated=True,
                method="saml",
                subject=claims.get("name_id", ""),
                tenant_id=claims.get("tenant_id"),
                groups=claims.get("groups", []),
                capabilities=claims.get("capabilities", []),
                metadata=claims,
            )
        except Exception as exc:
            logger.debug("SAML verify failed: %s", exc)
            return AuthResult(is_authenticated=False)

    async def _verify_mtls(self, cert_pem: str) -> AuthResult:
        """S183: mTLS client cert verification.

        Args:
            cert_pem: PEM-encoded client certificate.

        Returns:
            AuthResult с CN/subject.
        """
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
            logger.debug("mTLS verify failed: %s", exc)
            return AuthResult(is_authenticated=False)

    async def _is_blacklisted(self, jti: str) -> bool:
        """S183: check JWT blacklist.

        Args:
            jti: JWT ID.

        Returns:
            True если blacklisted (fail-closed на ошибке Redis недоступности).

        S202 audit fix: использует RedisJwtBlacklist с правильным redis
        client (не конструктор без аргументов), await для async ``is_revoked``.
        Fail-closed: если Redis недоступен — токен считается отозванным.
        """
        try:
            from src.backend.core.auth.jwt_blacklist import (
                RedisJwtBlacklist,
            )
            from src.backend.infrastructure.clients.storage.redis import (
                get_redis_client,
            )

            redis_client = await get_redis_client().get_client("cache")
            blacklist = RedisJwtBlacklist(redis_client)
            return await blacklist.is_revoked(jti)
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
            from src.backend.core.auth.admin_roles import (
                AdminRole,
                extract_admin_roles,
            )

            roles = extract_admin_roles(auth.metadata)
            if AdminRole.SUPER_ADMIN in roles:
                return True
        except Exception:
            # Fallback: если AdminRole import failed — НЕ bypass (fail-closed)
            pass

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
