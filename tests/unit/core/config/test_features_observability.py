"""Unit tests for src.backend.core.config.features.observability (T1.3.4 split)."""

from __future__ import annotations

import os

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.observability import ObservabilityFlags


class TestObservabilityFlagsClass:
    def test_observability_flags_importable(self) -> None:
        assert ObservabilityFlags is not None

    def test_observability_flags_instantiates(self) -> None:
        flags = ObservabilityFlags()
        assert flags.tracing_baggage_strict is False  # default-OFF feature flag
        assert flags.audit_clickhouse_enabled is False  # default-OFF feature flag

    def test_observability_env_vars(self) -> None:
        os.environ["FEATURE_TRACING_BAGGAGE_STRICT"] = "true"
        os.environ["FEATURE_AUDIT_CLICKHOUSE_ENABLED"] = "true"
        try:
            flags = ObservabilityFlags()
            assert flags.tracing_baggage_strict is True
            assert flags.audit_clickhouse_enabled is True
        finally:
            del os.environ["FEATURE_TRACING_BAGGAGE_STRICT"]
            del os.environ["FEATURE_AUDIT_CLICKHOUSE_ENABLED"]

    def test_observability_field_count(self) -> None:
        # 2 fields: tracing_baggage_strict + audit_clickhouse_enabled
        fields = ObservabilityFlags.model_fields
        obs_names = list(fields.keys())
        assert "tracing_baggage_strict" in obs_names
        assert "audit_clickhouse_enabled" in obs_names
        assert len(obs_names) == 2


class TestObservabilityFlagsComposition:
    def test_feature_flags_inherits_observability_fields(self) -> None:
        assert hasattr(feature_flags, "tracing_baggage_strict")
        assert hasattr(feature_flags, "audit_clickhouse_enabled")
        assert feature_flags.tracing_baggage_strict is False  # default-OFF feature flag
        assert feature_flags.audit_clickhouse_enabled is False  # default-OFF feature flag

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags

        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        assert "ObservabilityFlags" in mro_names
        # Также AuthFlags + SecurityFlags (T1.3.1 + T1.3.2)
        assert "AuthFlags" in mro_names
        assert "SecurityFlags" in mro_names
