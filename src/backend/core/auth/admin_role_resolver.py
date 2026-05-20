"""Mapping JWT-claim / SAML group / mTLS CN → :class:`AdminRole` (S13 K1 W2).

Поддерживает три источника ролей:

* JWT-claim ``admin_roles: list[str]`` (Keycloak/Auth0 client-roles);
* SAML attribute ``memberOf`` или ``Groups`` → mapping по правилам из конфига;
* mTLS — CN из ``x509`` сертификата сопоставляется с whitelist'ом из конфига.

Конфиг роуминга загружается из ``core/config/services/auth_admin_roles.toml``
(опционально; по умолчанию резолвер возвращает пустой набор ролей —
система продолжает работать в read-only режиме).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from src.backend.core.auth.admin_roles import AdminRole

__all__ = (
    "AdminRoleMapping",
    "resolve_jwt_admin_roles",
    "resolve_mtls_admin_roles",
    "resolve_saml_admin_roles",
)


@dataclass(frozen=True, slots=True)
class AdminRoleMapping:
    """Конфигурация маппинга внешних идентификаторов в admin-роли.

    Attributes:
        jwt_claim_name: Название claim в JWT с ролями (default ``admin_roles``).
        saml_group_to_role: SAML group → AdminRole.
        mtls_cn_to_role: x509 CN → AdminRole.
    """

    jwt_claim_name: str = "admin_roles"
    saml_group_to_role: dict[str, AdminRole] = field(default_factory=dict)
    mtls_cn_to_role: dict[str, AdminRole] = field(default_factory=dict)


def resolve_jwt_admin_roles(
    *,
    claims: dict[str, object],
    mapping: AdminRoleMapping,
) -> frozenset[AdminRole]:
    """Извлекает admin-роли из JWT claims."""
    raw = claims.get(mapping.jwt_claim_name)
    if raw is None:
        return frozenset()
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, Iterable):
        return frozenset()
    roles: set[AdminRole] = set()
    for value in raw:
        try:
            roles.add(AdminRole(str(value)))
        except ValueError:
            continue
    return frozenset(roles)


def resolve_saml_admin_roles(
    *,
    groups: Iterable[str],
    mapping: AdminRoleMapping,
) -> frozenset[AdminRole]:
    """SAML groups → AdminRole через конфигурируемый mapping."""
    roles: set[AdminRole] = set()
    for group in groups:
        role = mapping.saml_group_to_role.get(group)
        if role is not None:
            roles.add(role)
    return frozenset(roles)


def resolve_mtls_admin_roles(
    *,
    cn: str,
    mapping: AdminRoleMapping,
) -> frozenset[AdminRole]:
    """mTLS x509 CN → AdminRole через whitelist."""
    role = mapping.mtls_cn_to_role.get(cn)
    return frozenset({role}) if role else frozenset()
