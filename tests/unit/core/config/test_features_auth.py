"""Unit tests for src.backend.core.config.features.auth (T1.3.1 split).

Verifies:
1. AuthFlags class imports и instantiates
2. K1 — Auth fields (auth_joserfc, auth_mtls_client) доступны
3. FeatureFlags composition (multiple inheritance) работает
4. feature_flags singleton имеет все auth-поля
"""

from __future__ import annotations

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.auth import AuthFlags


class TestAuthFlagsClass:
    def test_auth_flags_importable(self) -> None:
        assert AuthFlags is not None

    def test_auth_flags_instantiates(self) -> None:
        flags = AuthFlags()
        assert flags.auth_joserfc is False
        assert flags.auth_mtls_client is False

    def test_auth_flags_has_env_prefix(self) -> None:
        # FEATURE_AUTH_JOSERFC=true → auth_joserfc=True
        import os

        os.environ["FEATURE_AUTH_JOSERFC"] = "true"
        try:
            flags = AuthFlags()
            assert flags.auth_joserfc is True
        finally:
            del os.environ["FEATURE_AUTH_JOSERFC"]

    def test_auth_flags_field_count(self) -> None:
        # Should have exactly 2 K1 — Auth fields
        fields = AuthFlags.model_fields
        auth_field_names = [name for name in fields if name.startswith("auth_")]
        assert "auth_joserfc" in auth_field_names
        assert "auth_mtls_client" in auth_field_names
        # 2 K1 — Auth fields only (T1.3.1 scope)
        assert len(auth_field_names) == 2


class TestFeatureFlagsComposition:
    """Verify multiple inheritance: FeatureFlags(AuthFlags, BaseSettingsWithLoader)."""

    def test_feature_flags_inherits_auth_fields(self) -> None:
        # feature_flags singleton имеет auth_joserfc, auth_mtls_client через inheritance
        assert hasattr(feature_flags, "auth_joserfc")
        assert hasattr(feature_flags, "auth_mtls_client")
        assert feature_flags.auth_joserfc is False
        assert feature_flags.auth_mtls_client is False

    def test_feature_flags_inherits_other_flags(self) -> None:
        # Existing flags (waf, ai) still in __init__.py
        assert hasattr(feature_flags, "waf_outbound_via_facade")
        assert hasattr(feature_flags, "ai_gateway_enforce")

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags

        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        # AuthFlags должен быть в MRO
        assert "AuthFlags" in mro_names
        # BaseSettingsWithLoader тоже
        assert "BaseSettingsWithLoader" in mro_names


class TestAuthFlagsBackwardsCompat:
    """884 import sites: from src.backend.core.config.features import feature_flags."""

    def test_singleton_unchanged(self) -> None:
        from src.backend.core.config.features import feature_flags as ff

        assert ff is feature_flags  # same singleton

    def test_field_default_values(self) -> None:
        # auth flags — default False
        assert feature_flags.auth_joserfc is False
        assert feature_flags.auth_mtls_client is False
