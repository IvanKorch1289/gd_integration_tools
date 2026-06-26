"""Unit tests for src.backend.core.config.features.plugins (T1.3.13 split)."""

from __future__ import annotations

import os

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.plugins import PluginsFlags


class TestPluginsFlagsClass:
    def test_plugins_flags_importable(self) -> None:
        assert PluginsFlags is not None

    def test_plugins_flags_instantiates(self) -> None:
        flags = PluginsFlags()
        for f in ("extensions_credit_workflow", "credit_pipeline_v2"):
            assert getattr(flags, f) is True, f"{f} default не False"

    def test_plugins_env_vars(self) -> None:
        os.environ["FEATURE_EXTENSIONS_CREDIT_WORKFLOW"] = "true"
        os.environ["FEATURE_CREDIT_PIPELINE_V2"] = "true"
        try:
            flags = PluginsFlags()
            assert flags.extensions_credit_workflow is True
            assert flags.credit_pipeline_v2 is True
        finally:
            del os.environ["FEATURE_EXTENSIONS_CREDIT_WORKFLOW"]
            del os.environ["FEATURE_CREDIT_PIPELINE_V2"]

    def test_plugins_field_count(self) -> None:
        fields = PluginsFlags.model_fields
        names = list(fields.keys())
        # 2 fields: 1 K9 Wave 4 + 1 T3 Sprint 7
        assert len(names) == 2


class TestPluginsFlagsComposition:
    def test_feature_flags_inherits_plugins_fields(self) -> None:
        for f in ("extensions_credit_workflow", "credit_pipeline_v2"):
            assert hasattr(feature_flags, f), f"feature_flags missing {f}"

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags

        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        # 12 mixins в MRO (T1.3.13)
        for cls in (
            "AuthFlags",
            "SecurityFlags",
            "ObservabilityFlags",
            "NetFlags",
            "PluginsFlags",
            "WorkflowFlags",
            "AIFlags",
            "DSLFlags",
            "ExperimentalFlags",
            "ResilienceFlags",
            "BillingFlags",
            "Sprint5Flags",
        ):
            assert cls in mro_names, f"{cls} missing в MRO"
