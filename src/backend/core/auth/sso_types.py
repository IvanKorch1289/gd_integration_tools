"""SSO types (Sprint 125 W2) — public DTOs для SSO-стека.

Per ADR-0054 §2: per-tenant IdP configuration в Vault с
``groups_to_capabilities`` mapping.

Используется:

* :class:`SsoRegistry` (read-through cache от Vault) — S125 W2.
* :class:`require_sso_auth` decorator — S125 W3.
* ``services/admin/sso.py`` (backward-compat shim) — S125 W4.

Public API (экспортируется из ``core.auth``):

* :class:`SSOUserInfo` — аутентифицированный пользователь.
* :class:`IdpConfig` — per-tenant IdP config (Pydantic model).
* :class:`GroupsToCapabilities` — IdP groups → capability-scope'ы.

S20+ extensions (не реализовано в S125):

* Refresh token (cookie-based) — S126+.
* OIDC stub → impl — S126+.

Wave: s125-w2-sso-registry
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = (
    "GROUPS_TO_CAPABILITIES_KEY",
    "GroupsToCapabilities",
    "IdpConfig",
    "SSOUserInfo",
)

# Vault field name для groups-to-capabilities mapping (per ADR-0054 §2).
GROUPS_TO_CAPABILITIES_KEY = "groups_to_capabilities"

#: Sentinel for ``GroupsToCapabilities``: capability-scope формат ``"<name>:<scope>"``.
#: Пример: ``"admin.feature_flag:write"``. См. :class:`CapabilityGate`.


class GroupsToCapabilities(BaseModel):
    """IdP groups → capability-scope'ы mapping (per ADR-0054 §3).

    Ключ — IdP group (Okta ``groups`` claim, AzureAD ``wids`` claim,
    Keycloak ``roles``). Значение — список capability-scope'ов формата
    ``"<capability>:<scope>"``.

    Example::

        GroupsToCapabilities(
            mappings={
                "bank-admins": ["admin.feature_flag:write", "admin.tenants:read"],
                "bank-users": ["user.profile:read"],
            }
        )
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    mappings: dict[str, list[str]] = Field(
        default_factory=dict, description="IdP group → список capability-scope'ов."
    )

    def resolve(self, groups: list[str]) -> list[str]:
        """Возвращает union всех capability-scope'ов для данных groups.

        Args:
            groups: IdP-группы пользователя (из SSO claims).

        Returns:
            Дедуплицированный список capability-scope'ов (порядок
            сохраняется — дедупликация first-seen).
        """
        resolved: list[str] = []
        seen: set[str] = set()
        for group in groups:
            for cap in self.mappings.get(group, []):
                if cap not in seen:
                    resolved.append(cap)
                    seen.add(cap)
        return resolved


class IdpConfig(BaseModel):
    """Per-tenant IdP configuration record (per ADR-0054 §2).

    Attributes:
        entity_id: IdP entity-id (SAML).
        sso_url: IdP SAML SSO URL.
        x509_cert: Публичный сертификат IdP (PEM).
        allow_create_user: Автопровижинг нового пользователя.
        slo_url: Single Logout URL (опционально).
        groups_to_capabilities: IdP groups → capability-scope'ы mapping.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: str = Field(..., min_length=1, description="IdP entity-id (SAML).")
    sso_url: str = Field(..., min_length=1, description="IdP SAML SSO URL.")
    x509_cert: str = Field(
        ..., min_length=1, description="Публичный сертификат IdP (PEM)."
    )
    slo_url: str | None = Field(
        default=None, description="Single Logout URL (опционально)."
    )
    allow_create_user: bool = Field(
        default=False,
        description="Автопровижинг нового пользователя при первом SSO-login.",
    )
    groups_to_capabilities: GroupsToCapabilities = Field(
        default_factory=GroupsToCapabilities,
        description="IdP groups → capability-scope'ы mapping.",
    )


class SSOUserInfo:
    """Данные аутентифицированного пользователя из SSO.

    Создаётся в S125 W3 (require_sso_auth decorator) при успешной
    SAML AuthnResponse. Содержит ``sub`` (IdP subject), email, name,
    groups, roles.

    Не Pydantic модель — это **runtime DTO**, не DTO для сериализации
    (для JWT claims используется отдельный :class:`SamlAuthResult`).
    """

    def __init__(
        self,
        *,
        sub: str,
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
