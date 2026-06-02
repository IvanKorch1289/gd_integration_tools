"""Unit tests for core.auth.admin_role_resolver (S38 T-P0.1.5).

Coverage target: admin_role_resolver.py 0% → 80%+.
Tests:
- resolve_jwt_admin_roles: list, str, missing claim, invalid value
- resolve_saml_admin_roles: matched, unmatched, empty
- resolve_mtls_admin_roles: matched, unmatched
- AdminRoleMapping: defaults
"""

from __future__ import annotations

import pytest

from src.backend.core.auth.admin_role_resolver import (
    AdminRoleMapping,
    resolve_jwt_admin_roles,
    resolve_mtls_admin_roles,
    resolve_saml_admin_roles,
)
from src.backend.core.auth.admin_roles import AdminRole


class TestResolveJwtAdminRoles:
    def test_missing_claim_returns_empty(self) -> None:
        mapping = AdminRoleMapping()
        result = resolve_jwt_admin_roles(claims={}, mapping=mapping)
        assert result == frozenset()

    def test_list_of_valid_roles(self) -> None:
        mapping = AdminRoleMapping()
        claims = {"admin_roles": ["super_admin", "operator"]}
        result = resolve_jwt_admin_roles(claims=claims, mapping=mapping)
        assert AdminRole.SUPER_ADMIN in result
        assert AdminRole.OPERATOR in result

    def test_single_string_role(self) -> None:
        mapping = AdminRoleMapping()
        claims = {"admin_roles": "super_admin"}
        result = resolve_jwt_admin_roles(claims=claims, mapping=mapping)
        assert result == frozenset({AdminRole.SUPER_ADMIN})

    def test_invalid_role_skipped(self) -> None:
        mapping = AdminRoleMapping()
        claims = {"admin_roles": ["super_admin", "INVALID_ROLE"]}
        result = resolve_jwt_admin_roles(claims=claims, mapping=mapping)
        assert result == frozenset({AdminRole.SUPER_ADMIN})

    def test_custom_claim_name(self) -> None:
        mapping = AdminRoleMapping(jwt_claim_name="custom_roles")
        claims = {"custom_roles": ["super_admin"], "admin_roles": ["operator"]}
        result = resolve_jwt_admin_roles(claims=claims, mapping=mapping)
        # Only reads custom_roles
        assert AdminRole.SUPER_ADMIN in result
        assert AdminRole.OPERATOR not in result

    def test_non_iterable_claim_returns_empty(self) -> None:
        mapping = AdminRoleMapping()
        claims = {"admin_roles": 42}  # int, not iterable
        result = resolve_jwt_admin_roles(claims=claims, mapping=mapping)
        assert result == frozenset()


class TestResolveSamlAdminRoles:
    def test_matched_groups(self) -> None:
        mapping = AdminRoleMapping(
            saml_group_to_role={
                "admins": AdminRole.SUPER_ADMIN,
                "ops": AdminRole.OPERATOR,
            }
        )
        result = resolve_saml_admin_roles(
            groups=["admins", "ops", "unknown"],
            mapping=mapping,
        )
        assert AdminRole.SUPER_ADMIN in result
        assert AdminRole.OPERATOR in result

    def test_empty_groups(self) -> None:
        mapping = AdminRoleMapping()
        result = resolve_saml_admin_roles(groups=[], mapping=mapping)
        assert result == frozenset()

    def test_unmatched_groups(self) -> None:
        mapping = AdminRoleMapping(
            saml_group_to_role={"admins": AdminRole.SUPER_ADMIN}
        )
        result = resolve_saml_admin_roles(groups=["random"], mapping=mapping)
        assert result == frozenset()


class TestResolveMtlsAdminRoles:
    def test_matched_cn(self) -> None:
        mapping = AdminRoleMapping(
            mtls_cn_to_role={"admin.example.com": AdminRole.SUPER_ADMIN}
        )
        result = resolve_mtls_admin_roles(
            cn="admin.example.com", mapping=mapping
        )
        assert result == frozenset({AdminRole.SUPER_ADMIN})

    def test_unmatched_cn(self) -> None:
        mapping = AdminRoleMapping(
            mtls_cn_to_role={"admin.example.com": AdminRole.SUPER_ADMIN}
        )
        result = resolve_mtls_admin_roles(cn="other.example.com", mapping=mapping)
        assert result == frozenset()

    def test_empty_mapping(self) -> None:
        mapping = AdminRoleMapping()
        result = resolve_mtls_admin_roles(cn="any", mapping=mapping)
        assert result == frozenset()


class TestAdminRoleMapping:
    def test_defaults(self) -> None:
        mapping = AdminRoleMapping()
        assert mapping.jwt_claim_name == "admin_roles"
        assert mapping.saml_group_to_role == {}
        assert mapping.mtls_cn_to_role == {}

    def test_custom(self) -> None:
        mapping = AdminRoleMapping(
            jwt_claim_name="roles",
            saml_group_to_role={"x": AdminRole.SUPER_ADMIN},
            mtls_cn_to_role={"y": AdminRole.SUPER_ADMIN},
        )
        assert mapping.jwt_claim_name == "roles"
        assert "x" in mapping.saml_group_to_role
        assert "y" in mapping.mtls_cn_to_role
