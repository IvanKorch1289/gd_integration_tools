"""Unit tests for src.backend.core.config.features.experimental (T1.3.9 split)."""

from __future__ import annotations

import os

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.experimental import ExperimentalFlags


class TestExperimentalFlagsClass:
    def test_experimental_flags_importable(self) -> None:
        assert ExperimentalFlags is not None

    def test_experimental_flags_instantiates(self) -> None:
        flags = ExperimentalFlags()
        for f in (
            "eventbus_facade",
            "eventbus_file_watcher",
            "activity_capability_gate_enabled",
            "ai_workflow_activity_enabled",
            "openfeature_external",
            "plugin_semver_strict",
            "frontend_plugin_marketplace",
        ):
            assert getattr(flags, f) is False, f"{f} default не False"

    def test_experimental_env_vars(self) -> None:
        os.environ["FEATURE_EVENTBUS_FACADE"] = "true"
        os.environ["FEATURE_OPENFEATURE_EXTERNAL"] = "true"
        try:
            flags = ExperimentalFlags()
            assert flags.eventbus_facade is True
            assert flags.openfeature_external is True
        finally:
            del os.environ["FEATURE_EVENTBUS_FACADE"]
            del os.environ["FEATURE_OPENFEATURE_EXTERNAL"]

    def test_experimental_field_count(self) -> None:
        fields = ExperimentalFlags.model_fields
        names = list(fields.keys())
        # 7 experimental fields (T1.3.9 scope)
        assert len(names) == 7


class TestExperimentalFlagsComposition:
    def test_feature_flags_inherits_experimental_fields(self) -> None:
        for f in (
            "eventbus_facade",
            "eventbus_file_watcher",
            "activity_capability_gate_enabled",
            "ai_workflow_activity_enabled",
            "openfeature_external",
            "plugin_semver_strict",
            "frontend_plugin_marketplace",
        ):
            assert hasattr(feature_flags, f), f"feature_flags missing {f}"

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags
        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        # 8 mixins в MRO
        for cls in ("AuthFlags", "SecurityFlags", "ObservabilityFlags",
                    "NetFlags", "WorkflowFlags", "AIFlags", "DSLFlags",
                    "ExperimentalFlags"):
            assert cls in mro_names, f"{cls} missing в MRO"
        # ВСЕ 9 ORIGINAL DOMAINS extracted (T1.3.1 — T1.3.9 = 8 mixins, 9th is the experimental)

    def test_t1_3_plan_complete(self) -> None:
        """Verify that all 9 T1.3.x PRs из плана extracted (8 mixins + experimental in same)."""
        from src.backend.core.config.features import FeatureFlags
        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        # 8 mixins от T1.3.1 до T1.3.9 (8th = ExperimentalFlags)
        expected_mixins = [
            "AuthFlags",          # T1.3.1
            "SecurityFlags",      # T1.3.2
            "ObservabilityFlags", # T1.3.4
            "NetFlags",           # T1.3.5
            "WorkflowFlags",      # T1.3.6
            "AIFlags",            # T1.3.7
            "DSLFlags",           # T1.3.8
            "ExperimentalFlags",  # T1.3.9
        ]
        for cls in expected_mixins:
            assert cls in mro_names, f"T1.3 split {cls} missing"
