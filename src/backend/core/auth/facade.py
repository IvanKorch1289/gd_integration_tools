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
from src.backend.core.auth.facade_core_mixin import AuthCoreMixin
from src.backend.core.auth.facade_token_mixin import AuthTokenMixin
from src.backend.core.auth.facade_verify_mixin import AuthVerifyMixin
from src.backend.core.logging import get_logger

__all__ = ("AuthFacade", "AuthResult", "get_auth_facade")

logger = get_logger(__name__)


# S61 M2-#1: AuthResult extracted в :mod:`auth_result` (data class only,
# no methods, no I/O). Re-exported ниже для backward-compat public API.


class AuthFacade(AuthTokenMixin, AuthVerifyMixin, AuthCoreMixin):
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
