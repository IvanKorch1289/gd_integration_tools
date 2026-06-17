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

    async def verify_request(
        self,
        token: str,
        *,
        method: str = "jwt",
    ) -> AuthResult:
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
                # API key validation — uses ldap_client_factory or local registry.
                # Per backend agnostic — for now, return unauthenticated.
                logger.debug("api_key verification not yet implemented in facade")
                return AuthResult(is_authenticated=False)
        except Exception as exc:
            logger.debug("verify_request failed: %s", exc)
            return AuthResult(
                is_authenticated=False,
                metadata={"error": str(exc)},
            )
        return AuthResult(is_authenticated=False)

    def check_permission(
        self,
        auth: AuthResult,
        required_capability: str,
    ) -> bool:
        """S164 W2: check if authenticated subject has required capability.

        Args:
            auth: :class:`AuthResult` from :meth:`verify_request`.
            required_capability: Capability name (e.g. ``"admin.read.capabilities"``).

        Returns:
            ``True`` if subject has capability OR is_admin.
        """
        if not auth.is_authenticated:
            return False
        # Admin bypass — superusers can do anything.
        if "admin" in auth.groups:
            return True
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