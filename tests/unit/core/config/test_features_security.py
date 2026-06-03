"""Unit tests for src.backend.core.config.features.security (T1.3.2 split)."""

from __future__ import annotations

import os

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.security import SecurityFlags


class TestSecurityFlagsClass:
    def test_security_flags_importable(self) -> None:
        assert SecurityFlags is not None

    def test_security_flags_instantiates(self) -> None:
        flags = SecurityFlags()
        assert flags.vault_rotation_enabled is False

    def test_vault_rotation_via_env_var(self) -> None:
        os.environ["FEATURE_VAULT_ROTATION_ENABLED"] = "true"
        try:
            flags = SecurityFlags()
            assert flags.vault_rotation_enabled is True
        finally:
            del os.environ["FEATURE_VAULT_ROTATION_ENABLED"]

    def test_security_flags_field_count(self) -> None:
        fields = SecurityFlags.model_fields
        security_names = [n for n in fields if n.startswith("vault_")]
        assert "vault_rotation_enabled" in security_names
        # 1 field only (T1.3.2 scope)
        assert len(security_names) == 1


class TestSecurityFlagsComposition:
    def test_feature_flags_inherits_vault_field(self) -> None:
        assert hasattr(feature_flags, "vault_rotation_enabled")
        assert feature_flags.vault_rotation_enabled is False

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags
        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        assert "SecurityFlags" in mro_names
