"""Unit tests for src.backend.core.config.features.sprints_15_17 (T1.3.19 split).

Subagent #1 (Sprint 15+17) created sprints_15_17.py but timed out
before test creation. Orchestrator завершил.
"""

from __future__ import annotations

import os

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.sprints_15_17 import Sprints1517Flags


class TestSprints1517FlagsClass:
    def test_sprints_15_17_flags_importable(self) -> None:
        assert Sprints1517Flags is not None

    def test_sprints_15_17_flags_instantiates(self) -> None:
        flags = Sprints1517Flags()
        expected = [
            "sandbox_amortised_psutil",
            "arch_map_llm_search_enabled",
            "ai_pr_review_enabled",
            "dsl_visual_editor_drag_drop",
            "changelog_autogen_enabled",
            "config_validator_enabled",
            "metrics_registry_strict",
            "task_registry_strict",
            "apscheduler_metrics",
            "authz_gateway_enabled",
            "audit_correlation_required",
            "tenant_feature_flag_ui",
            "resilience_coordinator_enabled",
            "routes_capability_gate_strict",
            "routes_tenant_aware_strict",
            "call_function_whitelist_strict",
            "saga_state_persistence_enabled",
        ]
        for f in expected:
            assert getattr(flags, f) is False, f"{f} default не False"

    def test_sprints_15_17_env_vars(self) -> None:
        os.environ["FEATURE_AI_PR_REVIEW_ENABLED"] = "true"
        os.environ["FEATURE_AUTHZ_GATEWAY_ENABLED"] = "true"
        try:
            flags = Sprints1517Flags()
            assert flags.ai_pr_review_enabled is True
            assert flags.authz_gateway_enabled is True
        finally:
            del os.environ["FEATURE_AI_PR_REVIEW_ENABLED"]
            del os.environ["FEATURE_AUTHZ_GATEWAY_ENABLED"]

    def test_sprints_15_17_field_count(self) -> None:
        fields = Sprints1517Flags.model_fields
        names = list(fields.keys())
        # 17 fields: Sprint 15 (5) + Sprint 17 (12)
        assert len(names) == 17


class TestSprints1517FlagsComposition:
    def test_feature_flags_inherits_sprints_15_17_fields(self) -> None:
        for f in (
            "arch_map_llm_search_enabled",
            "authz_gateway_enabled",
            "audit_correlation_required",
            "tenant_feature_flag_ui",
            "saga_state_persistence_enabled",
        ):
            assert hasattr(feature_flags, f), f"feature_flags missing {f}"

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags

        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        for cls in ("Sprints1517Flags", "Sprints1821Flags", "Sprints2427Flags"):
            assert cls in mro_names, f"{cls} missing в MRO"
