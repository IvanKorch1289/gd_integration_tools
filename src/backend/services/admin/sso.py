"""SSO stubs (Sprint 19 K5 W5b): SAML / AD / OIDC placeholders.

Wave: s19/k5-w5b

Этот модуль содержит placeholder-классы для SSO-интеграции.
Реальная реализация планируется в S20+ после выбора identity provider.

Stub-ы:
    - SamlSSOClient       — SAML 2.0 SP integration (Okta / ADFS / Azure AD)
    - OidcSSOClient       — OIDC/OAuth2 PKCE flow
    - AdminSSOConfig      — конфигурация из admin UI
    - require_sso_auth     — decorator для admin endpoints (TODO S20)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

__all__ = (
    "SamlSSOClient",
    "OidcSSOClient",
    "AdminSSOConfig",
    "SSOUserInfo",
    "require_sso_auth",
)


class SSOUserInfo:
    """Данные аутентифицированного пользователя из SSO."""

    def __init__(
        self,
        *,
        sub: str,  # SSO subject (user id)
        email: str | None = None,
        name: str | None = None,
        groups: list[str] | None = None,
        roles: list[str] | None = None,
    ) -> None:
        self.sub = sub
        self.email = email
        self.name = name
        self.groups = list(groups) if groups else []
        self.roles = list(roles) if roles else []


class AdminSSOConfig:
    """
    SSO configuration record (persisted to DB / config file, S20+).

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


class SamlSSOClient(ABC):
    """
    SAML 2.0 Service Provider stub.

    Реализация S20+ (TBD):
        - python3-saml / onelogin-saml
        - Assertion Consumer Service (ACS) endpoint
        - SP metadata generation
        - NameID mapping to internal user
    """

    def __init__(self, config: AdminSSOConfig) -> None:
        self._cfg = config

    @abstractmethod
    def get_login_url(self, *, return_to: str) -> str:
        """Возвращает URL для redirect на IdP."""
        raise NotImplementedError("SAML login URL — implement in S20+")

    @abstractmethod
    def get_logout_url(self, *, return_to: str) -> str:
        """Возвращает URL для Single Logout."""
        raise NotImplementedError("SAML logout URL — implement in S20+")

    @abstractmethod
    async def handle_acs_response(self, *, saml_response: str) -> SSOUserInfo:
        """Обрабатывает SAML Response от IdP. Returns SSOUserInfo."""
        raise NotImplementedError("SAML ACS handler — implement in S20+")


class OidcSSOClient(ABC):
    """
    OIDC/OAuth2 PKCE stub.

    Реализация S20+ (TBD):
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
        raise NotImplementedError("OIDC auth URL — implement in S20+")

    @abstractmethod
    async def exchange_code(self, *, code: str, code_verifier: str) -> SSOUserInfo:
        """Обменивает authorization code на tokens, returns SSOUserInfo."""
        raise NotImplementedError("OIDC token exchange — implement in S20+")


# TODO S20: decorator for admin endpoints
def require_sso_auth(resource: str, action: str) -> Any:
    """
    Decorator для admin endpoints — enforces SSO auth + AuthZ (S20+).

    usage::

        @require_sso_auth("admin.feature_flag", "write")
        async def toggle_flag(request: Request) -> Response:
            ...

    S20 implementation will:
        1. Validate session/JWT from SSO provider
        2. Call AuthorizationGateway with principal = SSOUserInfo.sub
        3. Map SSO groups → RBAC roles
    """

    def decorator(fn: Any) -> Any:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            logger.debug("require_sso_auth placeholder for %s/%s", resource, action)
            # S20: implement SSO validation + AuthZ
            return fn(*args, **kwargs)

        return wrapper

    return decorator
