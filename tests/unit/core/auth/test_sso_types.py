"""Tests for ``src.backend.core.auth.sso_types``.

Sprint 125 W2: public DTOs для SSO-стека.
- GroupsToCapabilities (Pydantic frozen): IdP groups → capability-scope'ы
- IdpConfig (Pydantic frozen): per-tenant IdP config record
- SSOUserInfo: runtime DTO с default factory lists

Тесты фиксируют контракт:
- Pydantic frozen + extra='forbid' → mutation raises, extra fields raises
- resolve(): дедупликация first-seen, union по всем groups
- Required fields (entity_id, sso_url, x509_cert) с min_length=1
- SSOUserInfo: defaults для None lists
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.backend.core.auth.sso_types import (
    GROUPS_TO_CAPABILITIES_KEY,
    GroupsToCapabilities,
    IdpConfig,
    SSOUserInfo,
)


# ── GROUPS_TO_CAPABILITIES_KEY constant ──────────────────────────────


class TestGroupsToCapabilitiesKey:
    """Vault field name constant (ADR-0054 §2)."""

    def test_value(self) -> None:
        assert GROUPS_TO_CAPABILITIES_KEY == "groups_to_capabilities"

    def test_is_string(self) -> None:
        assert isinstance(GROUPS_TO_CAPABILITIES_KEY, str)


# ── GroupsToCapabilities ────────────────────────────────────────────


class TestGroupsToCapabilitiesConstruction:
    """Pydantic model с mappings dict."""

    def test_empty_default(self) -> None:
        g2c = GroupsToCapabilities()
        assert g2c.mappings == {}

    def test_with_mappings(self) -> None:
        g2c = GroupsToCapabilities(
            mappings={
                "bank-admins": ["admin.feature_flag:write"],
                "bank-users": ["user.profile:read"],
            }
        )
        assert g2c.mappings == {
            "bank-admins": ["admin.feature_flag:write"],
            "bank-users": ["user.profile:read"],
        }

    def test_mappings_default_factory_isolation(self) -> None:
        """Каждый инстанс получает свой dict (default_factory isolation)."""
        g1 = GroupsToCapabilities()
        g2 = GroupsToCapabilities()
        g1.mappings["new"] = ["x"]
        assert g2.mappings == {}


class TestGroupsToCapabilitiesFrozen:
    """Pydantic ConfigDict(frozen=True, extra='forbid')."""

    def test_assignment_raises(self) -> None:
        g2c = GroupsToCapabilities()
        with pytest.raises(ValidationError):
            g2c.mappings = {"x": ["y"]}  # type: ignore[misc]

    def test_extra_field_forbidden(self) -> None:
        """``extra='forbid'`` — неизвестные поля rejected."""
        with pytest.raises(ValidationError) as exc_info:
            GroupsToCapabilities(unknown_field="x")  # type: ignore[call-arg]
        assert "unknown_field" in str(exc_info.value)


class TestGroupsToCapabilitiesResolve:
    """Метод resolve(): union + дедупликация first-seen."""

    def test_resolve_empty(self) -> None:
        g2c = GroupsToCapabilities()
        assert g2c.resolve([]) == []
        assert g2c.resolve(["unknown"]) == []

    def test_resolve_single_group(self) -> None:
        g2c = GroupsToCapabilities(
            mappings={"admins": ["admin.feature_flag:write", "admin.tenants:read"]}
        )
        assert g2c.resolve(["admins"]) == [
            "admin.feature_flag:write",
            "admin.tenants:read",
        ]

    def test_resolve_multiple_groups(self) -> None:
        g2c = GroupsToCapabilities(
            mappings={
                "admins": ["admin.feature_flag:write"],
                "users": ["user.profile:read"],
            }
        )
        result = g2c.resolve(["admins", "users"])
        # Union: оба списка, порядок first-seen
        assert result == ["admin.feature_flag:write", "user.profile:read"]

    def test_resolve_dedup_first_seen(self) -> None:
        """Дубликат из разных groups — берётся первый seen."""
        g2c = GroupsToCapabilities(
            mappings={
                "admins": ["admin.feature_flag:write", "shared:read"],
                "users": ["shared:read", "user.profile:read"],
            }
        )
        result = g2c.resolve(["admins", "users"])
        # "shared:read" — из admins первый, не дублируется
        assert result == [
            "admin.feature_flag:write",
            "shared:read",
            "user.profile:read",
        ]

    def test_resolve_preserves_input_order(self) -> None:
        g2c = GroupsToCapabilities(
            mappings={
                "z": ["z-cap"],
                "a": ["a-cap"],
                "m": ["m-cap"],
            }
        )
        result = g2c.resolve(["z", "a", "m"])
        # Порядок по input groups (z, a, m), не по алфавиту
        assert result == ["z-cap", "a-cap", "m-cap"]

    def test_resolve_unknown_group_skipped(self) -> None:
        """Группы, которых нет в mappings, — silently skip."""
        g2c = GroupsToCapabilities(mappings={"known": ["cap"]})
        assert g2c.resolve(["known", "unknown", "another-unknown"]) == ["cap"]


# ── IdpConfig ────────────────────────────────────────────────────────


class TestIdpConfigConstruction:
    """Pydantic model с required fields и defaults."""

    def test_minimal_construction(self) -> None:
        cfg = IdpConfig(
            entity_id="https://idp.example.com/saml",
            sso_url="https://idp.example.com/sso",
            x509_cert="-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----",
        )
        assert cfg.entity_id == "https://idp.example.com/saml"
        assert cfg.sso_url == "https://idp.example.com/sso"
        assert cfg.x509_cert.startswith("-----BEGIN")
        assert cfg.slo_url is None
        assert cfg.allow_create_user is False
        assert cfg.groups_to_capabilities.mappings == {}

    def test_full_construction(self) -> None:
        cfg = IdpConfig(
            entity_id="eid",
            sso_url="url",
            x509_cert="cert",
            slo_url="https://idp.example.com/slo",
            allow_create_user=True,
            groups_to_capabilities=GroupsToCapabilities(
                mappings={"admins": ["admin:write"]}
            ),
        )
        assert cfg.slo_url == "https://idp.example.com/slo"
        assert cfg.allow_create_user is True
        assert cfg.groups_to_capabilities.mappings == {"admins": ["admin:write"]}


class TestIdpConfigValidation:
    """Pydantic constraints (min_length=1, extra='forbid')."""

    @pytest.mark.parametrize(
        "field,empty_value",
        [
            ("entity_id", ""),
            ("sso_url", ""),
            ("x509_cert", ""),
        ],
    )
    def test_min_length_one(self, field: str, empty_value: str) -> None:
        """min_length=1 — пустая строка rejected."""
        valid = {
            "entity_id": "eid",
            "sso_url": "url",
            "x509_cert": "cert",
        }
        valid[field] = empty_value
        with pytest.raises(ValidationError) as exc_info:
            IdpConfig(**valid)  # type: ignore[arg-type]
        assert field in str(exc_info.value)

    def test_missing_required_field(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            IdpConfig(sso_url="url", x509_cert="cert")  # type: ignore[call-arg]
        assert "entity_id" in str(exc_info.value)

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            IdpConfig(
                entity_id="e",
                sso_url="u",
                x509_cert="c",
                unknown="x",  # type: ignore[call-arg]
            )


class TestIdpConfigFrozen:
    """Frozen Pydantic — assignment raises."""

    def test_assignment_raises(self) -> None:
        cfg = IdpConfig(entity_id="e", sso_url="u", x509_cert="c")
        with pytest.raises(ValidationError):
            cfg.entity_id = "new"  # type: ignore[misc]


# ── SSOUserInfo ──────────────────────────────────────────────────────


class TestSSOUserInfoConstruction:
    """Runtime DTO с keyword-only init."""

    def test_minimal_construction(self) -> None:
        info = SSOUserInfo(sub="user-123")
        assert info.sub == "user-123"
        assert info.email is None
        assert info.name is None
        assert info.groups == []
        assert info.roles == []

    def test_full_construction(self) -> None:
        info = SSOUserInfo(
            sub="user-123",
            email="user@example.com",
            name="John Doe",
            groups=["admins", "users"],
            roles=["role-1"],
        )
        assert info.sub == "user-123"
        assert info.email == "user@example.com"
        assert info.name == "John Doe"
        assert info.groups == ["admins", "users"]
        assert info.roles == ["role-1"]

    def test_none_groups_becomes_empty_list(self) -> None:
        """``None`` для groups/roles → пустой list (default-factory pattern)."""
        info = SSOUserInfo(sub="x", groups=None, roles=None)
        assert info.groups == []
        assert info.roles == []

    def test_empty_groups_becomes_empty_list(self) -> None:
        info = SSOUserInfo(sub="x", groups=[], roles=[])
        assert info.groups == []
        assert info.roles == []

    def test_list_copy_isolation(self) -> None:
        """Переданный list копируется — mutation не затрагивает DTO."""
        source_groups = ["a", "b"]
        info = SSOUserInfo(sub="x", groups=source_groups)
        source_groups.append("c")
        assert info.groups == ["a", "b"]


class TestSSOUserInfoSignature:
    """__init__ keyword-only args."""

    def test_keyword_only(self) -> None:
        """Все параметры после ``*`` — keyword-only."""
        import inspect

        sig = inspect.signature(SSOUserInfo.__init__)
        params = sig.parameters

        # Все (включая self) — keyword-only? Нет: self — POSITIONAL_OR_KEYWORD,
        # все остальные — KEYWORD_ONLY.
        assert params["self"].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
        non_self = {k: v for k, v in params.items() if k != "self"}
        assert all(p.kind == p.KEYWORD_ONLY for p in non_self.values())

        # Required: только sub
        assert non_self["sub"].default is inspect.Parameter.empty
        # Optional: остальные
        for name in ("email", "name", "groups", "roles"):
            assert non_self[name].default is None


class TestSsoTypesExports:
    """``__all__`` exports."""

    def test_exports(self) -> None:
        from src.backend.core.auth import sso_types

        expected = {
            "GROUPS_TO_CAPABILITIES_KEY",
            "GroupsToCapabilities",
            "IdpConfig",
            "SSOUserInfo",
        }
        assert set(sso_types.__all__) == expected
