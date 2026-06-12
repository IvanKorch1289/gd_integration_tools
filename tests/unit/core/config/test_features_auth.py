"""Unit tests for src.backend.core.config.features.auth (T1.3.1 split).

Verifies:
1. AuthFlags class imports и instantiates
2. K1 — Auth field (auth_mtls_client) доступен
3. FeatureFlags composition (multiple inheritance) работает
4. feature_flags singleton имеет все auth-поля
5. S68 W1: ``auth_joserfc`` field полностью удалён (TD-S67-feature-flag-deprecation)
"""

from __future__ import annotations

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.auth import AuthFlags


class TestAuthFlagsClass:
    def test_auth_flags_importable(self) -> None:
        assert AuthFlags is not None

    def test_auth_flags_instantiates(self) -> None:
        flags = AuthFlags()
        assert flags.auth_mtls_client is False

    def test_auth_flags_has_env_prefix(self) -> None:
        # FEATURE_AUTH_MTLS_CLIENT=true → auth_mtls_client=True
        import os

        os.environ["FEATURE_AUTH_MTLS_CLIENT"] = "true"
        try:
            flags = AuthFlags()
            assert flags.auth_mtls_client is True
        finally:
            del os.environ["FEATURE_AUTH_MTLS_CLIENT"]

    def test_auth_flags_field_count(self) -> None:
        # S68 W1: ``auth_joserfc`` удалён (S67 W2 сделал no-op после deletion
        # ``jwt_backend_joserfc.py`` shim). ``AuthFlags`` теперь пустой
        # класс (резерв для future K1 — Auth flags).
        fields = AuthFlags.model_fields
        auth_field_names = [name for name in fields if name.startswith("auth_")]
        assert "auth_joserfc" not in auth_field_names
        # S68 W1 fix: auth_mtls_client оставлен (ТОЛЬКО auth_joserfc в scope cleanup)
        assert "auth_mtls_client" in auth_field_names
        # 1 K1 — Auth field (auth_mtls_client) после S68 W1 cleanup
        assert len(auth_field_names) == 1


class TestFeatureFlagsComposition:
    """Verify multiple inheritance: FeatureFlags(AuthFlags, BaseSettingsWithLoader)."""

    def test_feature_flags_inherits_auth_fields(self) -> None:
        # feature_flags singleton имеет auth_mtls_client через inheritance
        assert hasattr(feature_flags, "auth_mtls_client")
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
        # auth flag — default False
        assert feature_flags.auth_mtls_client is False


class TestAuthJoserfcFlagRemoved:
    """S68 W1: ``auth_joserfc`` field должен быть полностью удалён.

    Reference: TD-S67-feature-flag-deprecation. S67 W2 удалил
    ``jwt_backend_joserfc.py`` shim, flag стал no-op. S68 W1 cleanup —
    field удалён, dead branch в ``jwt_backend.py::verify()`` убран.
    """

    def test_auth_joserfc_not_in_auth_flags_fields(self) -> None:
        # Field не должен существовать в AuthFlags.model_fields
        assert "auth_joserfc" not in AuthFlags.model_fields

    def test_auth_joserfc_not_in_feature_flags_singleton(self) -> None:
        # feature_flags singleton не должен иметь auth_joserfc attribute
        assert not hasattr(feature_flags, "auth_joserfc")

    def test_feature_env_auth_joserfc_silently_ignored(self) -> None:
        # pydantic-settings с extra="forbid" выбросит ValidationError,
        # НО только если Field validation triggers. Поскольку поля больше
        # нет, env var не должен влиять на AuthFlags. Проверяем что
        # AuthFlags() с заданным FEATURE_AUTH_JOSERFC не падает (поле
        # просто игнорируется — settings source не находит matching field).
        import os

        os.environ["FEATURE_AUTH_JOSERFC"] = "true"
        try:
            # Не должно бросать исключение. Поскольку extra="forbid" на
            # model_config — pydantic-settings игнорирует unknown env vars
            # (не ValidationError, а просто молча).
            flags = AuthFlags()
            assert not hasattr(flags, "auth_joserfc")
        finally:
            del os.environ["FEATURE_AUTH_JOSERFC"]
