"""Unit tests for src.backend.core.config.features.sprint7 (T1.3.15 split)."""

from __future__ import annotations

import os

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.sprint7 import Sprint7Flags


class TestSprint7FlagsClass:
    def test_sprint7_flags_importable(self) -> None:
        assert Sprint7Flags is not None

    def test_sprint7_flags_instantiates(self) -> None:
        flags = Sprint7Flags()
        for f in (
            "multi_agent_supervisor_enabled",
            "voice_image_gen_enabled",
            "voice_stt_tts_enabled",
            "dsl_blueprints_migrate",
            "workflow_versioning_strict",
        ):
            assert getattr(flags, f) is False, f"{f} default не False"

    def test_sprint7_env_vars(self) -> None:
        os.environ["FEATURE_MULTI_AGENT_SUPERVISOR_ENABLED"] = "true"
        os.environ["FEATURE_WORKFLOW_VERSIONING_STRICT"] = "true"
        os.environ["FEATURE_DSL_BLUEPRINTS_MIGRATE"] = "true"
        try:
            flags = Sprint7Flags()
            assert flags.multi_agent_supervisor_enabled is True
            assert flags.workflow_versioning_strict is True
            assert flags.dsl_blueprints_migrate is True
        finally:
            del os.environ["FEATURE_MULTI_AGENT_SUPERVISOR_ENABLED"]
            del os.environ["FEATURE_WORKFLOW_VERSIONING_STRICT"]
            del os.environ["FEATURE_DSL_BLUEPRINTS_MIGRATE"]

    def test_sprint7_field_count(self) -> None:
        fields = Sprint7Flags.model_fields
        names = list(fields.keys())
        # 5 fields: 3 Sprint 7 K4 AI+RAG + 2 Sprint 7 K3 DSL+Workflow
        assert len(names) == 5, f"expected 5, got {len(names)}: {names}"


class TestSprint7FlagsComposition:
    def test_feature_flags_inherits_sprint7_fields(self) -> None:
        for f in (
            "multi_agent_supervisor_enabled",
            "voice_image_gen_enabled",
            "voice_stt_tts_enabled",
            "dsl_blueprints_migrate",
            "workflow_versioning_strict",
        ):
            assert hasattr(feature_flags, f), f"feature_flags missing {f}"

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags
        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        # 13 mixins в MRO (после T1.3.15)
        for cls in (
            "AuthFlags", "SecurityFlags", "ObservabilityFlags",
            "NetFlags", "PluginsFlags", "WorkflowFlags",
            "AIFlags", "DSLFlags", "ExperimentalFlags",
            "ResilienceFlags", "BillingFlags",
            "Sprint5Flags", "Sprint6Flags", "Sprint7Flags",
        ):
            assert cls in mro_names, f"{cls} missing в MRO"
