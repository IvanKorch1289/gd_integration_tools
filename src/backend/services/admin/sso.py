"""Backward-compat shim для ``services.admin.sso`` (Sprint 125 W4).

.. deprecated::
    Use :mod:`src.backend.core.auth` напрямую. Этот модуль остаётся
    только для downstream consumers, которые импортировали из
    ``services.admin.sso`` до Sprint 125 (S125 W2+).

**Что изменилось в S125:**

* :class:`SSOUserInfo` — re-export из :mod:`core.auth.sso_types` (W2).
* :class:`SamlSSOClient` — alias на :class:`core.auth.SamlBackend`.
  API частично отличается (Sprint 19 API → Sprint 96 SAML API).
  Migration guide: см. :class:`SamlBackend.build_login_redirect_url`
  вместо ``get_login_url(return_to=...)``.
* :class:`OidcSSOClient` — остаётся ABC stub. OIDC не реализован в S125
  (отложен на S126+ per ADR-0054 §5).
* :class:`AdminSSOConfig` — legacy class, сохранён для backward-compat.
  Новый код должен использовать :class:`core.auth.IdpConfig` +
  per-tenant Vault registry (:class:`core.auth.SsoRegistry`).
* :func:`require_sso_auth` — re-export нового API из :func:`core.auth.require_sso_auth`.
  Старый API (Sprint 19) ``require_sso_auth(resource, action)`` переименован
  в :func:`require_sso_auth_legacy` (no-op decorator + DeprecationWarning).
  Новый API (S125 W3): :func:`core.auth.require_sso_auth` (registry-based) +
  :func:`core.auth.require_sso_capability` для granular RBAC.

**Deprecation policy:** S125 (current) — warning. S127 — planned removal
(TD-0248 — добавить в backlog).

Wave: s125-w4-sso-shim
"""

from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from typing import Any

# --- core.auth re-exports (backward-compat) ------------------------------
from src.backend.core.auth import (
    GroupsToCapabilities,
    IdpConfig,
    RequireSsoAuthError,
    SamlBackend,
    SsoRegistry,
    SsoRegistryError,
    SsoRegistrySchemaError,
    SsoRegistryVaultError,
    SSOUserInfo,
    require_sso_auth,
    require_sso_capability,
)
from src.backend.core.logging import get_logger

__all__ = (
    "AdminSSOConfig",
    "GroupsToCapabilities",
    "IdpConfig",
    "OidcSSOClient",
    "RequireSsoAuthError",
    "SSOUserInfo",
    "SamlBackend",
    "SamlSSOClient",
    "SsoRegistry",
    "SsoRegistryError",
    "SsoRegistrySchemaError",
    "SsoRegistryVaultError",
    "require_sso_auth",
    "require_sso_auth_legacy",
    "require_sso_capability",
)

# Emitted при import модуля (singleton deprecation gate).
_DEPRECATION_MSG = (
    "src.backend.services.admin.sso is deprecated since S125; "
    "import from src.backend.core.auth instead "
    "(SsoRegistry, IdpConfig, require_sso_auth, SamlBackend, SSOUserInfo). "
    "This shim will be removed in S127 (TD-0248)."
)
warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)

_logger = get_logger(__name__)

# --- Aliases --------------------------------------------------------------

#: .. deprecated:: 1.0
#:     Use :class:`src.backend.core.auth.SamlBackend` directly.
SamlSSOClient = SamlBackend


# --- Legacy: AdminSSOConfig (Sprint 19 era) ------------------------------


class AdminSSOConfig:
    """
    Legacy SSO config (Sprint 19).

    .. deprecated::
        Use :class:`core.auth.IdpConfig` (per-tenant) +
        :class:`core.auth.SsoRegistry` (Vault-backed). Sprint 125 W2+.

    Attributes:
        provider:      ``saml`` | ``oidc``.
        metadata_url:  IdP metadata URL.
        client_id:     OAuth2/OIDC client_id.
        enabled:       SSO active для admin UI.
    """

    def __init__(
        self,
        *,
        provider: str,
        metadata_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        enabled: bool = False,
    ) -> None:
        if provider not in ("saml", "oidc"):
            raise ValueError(f"provider must be 'saml' or 'oidc', got {provider!r}")
        self.provider = provider
        self.metadata_url = metadata_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.enabled = enabled

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "metadata_url": self.metadata_url,
            "client_id": self.client_id,
            "enabled": self.enabled,
            # NOTE: client_secret redacted in API responses
        }


# --- OIDC stub (не реализован в S125) -----------------------------------


class OidcSSOClient(ABC):
    """
    OIDC/OAuth2 PKCE stub.

    .. deprecated::
        OIDC не реализован в S125 (per ADR-0054 §5 — SAML primary,
        OIDC deferred). Реализация планируется S126+.

    Реализация S126+ (TBD):
        - authlib / python-jose
        - Authorization Code + PKCE flow
        - ID token validation (RS256)
        - UserInfo endpoint
    """

    def __init__(self, config: AdminSSOConfig) -> None:
        self._cfg = config

    @abstractmethod
    def get_authorization_url(self, *, state: str, code_challenge: str) -> str:
        """Возвращает authorization endpoint URL."""
        raise NotImplementedError("OIDC auth URL — implement in S126+")

    @abstractmethod
    async def exchange_code(self, *, code: str, code_verifier: str) -> SSOUserInfo:
        """Обменивает authorization code на tokens, returns SSOUserInfo."""
        raise NotImplementedError("OIDC token exchange — implement in S126+")


# --- require_sso_auth_legacy (Sprint 19 API shim) ----------------------


def require_sso_auth_legacy(resource: str, action: str) -> Any:
    """
    Legacy SSO auth decorator (Sprint 19 API).

    .. deprecated::
        Use :func:`core.auth.require_sso_auth` (registry-based) +
        :func:`core.auth.require_sso_capability` для granular RBAC.

    Old API::

        @require_sso_auth_legacy("admin.feature_flag", "write")
        async def toggle_flag(...): ...

    New API::

        @require_sso_capability("admin.feature_flag:write", registry)
        async def toggle_flag(auth: AuthContext, ...): ...

    Legacy shim **not behavioral equivalent** — новый API требует
    SsoRegistry instance и принимает ``auth: AuthContext`` параметр.
    Здесь возвращается no-op decorator, который emit'ит warning при
    первом use, чтобы downstream код видел миграционные требования.

    Имя изменено на ``require_sso_auth_legacy`` чтобы не конфликтовать
    с new-API ``require_sso_auth`` (re-exported из core.auth).
    """
    warnings.warn(
        f"require_sso_auth_legacy(resource={resource!r}, action={action!r}) is "
        f"deprecated; use core.auth.require_sso_auth(registry) + "
        f"require_sso_capability('{resource}:{action}', registry). "
        f"See S125 W3 for new API.",
        DeprecationWarning,
        stacklevel=2,
    )

    def decorator(fn: Any) -> Any:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            _logger.debug(
                "Legacy require_sso_auth shim: %s/%s (no-op, migrate to core.auth)",
                resource,
                action,
            )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
