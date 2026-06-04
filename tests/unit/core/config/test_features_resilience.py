"""Unit tests for src.backend.core.config.features.resilience (T1.3.10 split)."""

from __future__ import annotations

import os

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.resilience import ResilienceFlags


class TestResilienceFlagsClass:
    def test_resilience_flags_importable(self) -> None:
        assert ResilienceFlags is not None

    def test_resilience_flags_instantiates(self) -> None:
        flags = ResilienceFlags()
        for f in (
            "auto_scaler_process_level",
            "auto_scaler_task_level",
            "k8s_hpa_exporter",
            "otel_asyncpg",
            "task_watchdog_deadline",
            "pool_health_monitor",
        ):
            assert getattr(flags, f) is False, f"{f} default не False"

    def test_resilience_env_vars(self) -> None:
        os.environ["FEATURE_AUTO_SCALER_PROCESS_LEVEL"] = "true"
        os.environ["FEATURE_OTEL_ASYNCPG"] = "true"
        try:
            flags = ResilienceFlags()
            assert flags.auto_scaler_process_level is True
            assert flags.otel_asyncpg is True
        finally:
            del os.environ["FEATURE_AUTO_SCALER_PROCESS_LEVEL"]
            del os.environ["FEATURE_OTEL_ASYNCPG"]

    def test_resilience_field_count(self) -> None:
        fields = ResilienceFlags.model_fields
        names = list(fields.keys())
        # 6 K3 Resilience + K8 Storage fields
        assert len(names) == 6


class TestResilienceFlagsComposition:
    def test_feature_flags_inherits_resilience_fields(self) -> None:
        for f in (
            "auto_scaler_process_level",
            "auto_scaler_task_level",
            "k8s_hpa_exporter",
            "otel_asyncpg",
            "task_watchdog_deadline",
            "pool_health_monitor",
        ):
            assert hasattr(feature_flags, f), f"feature_flags missing {f}"

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags

        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        # 9 mixins в MRO (8 original + ResilienceFlags)
        for cls in (
            "AuthFlags",
            "SecurityFlags",
            "ObservabilityFlags",
            "NetFlags",
            "WorkflowFlags",
            "AIFlags",
            "DSLFlags",
            "ExperimentalFlags",
            "ResilienceFlags",
        ):
            assert cls in mro_names, f"{cls} missing в MRO"
