"""Unit tests for src.backend.core.config.features.sprint19_ai (T1.3.24 split).

Subagent #3 (Sprint 19 second half) created sprint19_ai.py but
timeout prevented test creation. Orchestrator завершил.
"""

from __future__ import annotations

import os

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.sprint19_ai import Sprint19AIFlags


class TestSprint19AIFlagsClass:
    def test_sprint19_ai_flags_importable(self) -> None:
        assert Sprint19AIFlags is not None

    def test_sprint19_ai_flags_instantiates(self) -> None:
        flags = Sprint19AIFlags()
        expected = [
            "multi_replica_failover",
            "manage_py_diagnose",
            "adaptive_timeout_enabled",
            "vault_zero_downtime_rotation",
            "current_frames_fallback",
            "ai_safety_capability_unify",
            "prod_hot_reload_disable",
            "adaptive_rag_strategy_enabled",
            "quick_wins_pack",
            "admin_react_mvp",
            "dsl_usage_audit_enabled",
        ]
        for f in expected:
            assert getattr(flags, f) is False, f"{f} default не False"

    def test_sprint19_ai_env_vars(self) -> None:
        os.environ["FEATURE_ADAPTIVE_TIMEOUT_ENABLED"] = "true"
        os.environ["FEATURE_AI_SAFETY_CAPABILITY_UNIFY"] = "true"
        try:
            flags = Sprint19AIFlags()
            assert flags.adaptive_timeout_enabled is True
            assert flags.ai_safety_capability_unify is True
        finally:
            del os.environ["FEATURE_ADAPTIVE_TIMEOUT_ENABLED"]
            del os.environ["FEATURE_AI_SAFETY_CAPABILITY_UNIFY"]

    def test_sprint19_ai_field_count(self) -> None:
        fields = Sprint19AIFlags.model_fields
        names = list(fields.keys())
        # 11 fields: Sprint 19 second half (K2 Resilience + K4 AI + ops)
        assert len(names) == 11


class TestSprint19AIFlagsComposition:
    def test_feature_flags_inherits_sprint19_ai_fields(self) -> None:
        for f in (
            "adaptive_timeout_enabled",
            "vault_zero_downtime_rotation",
            "ai_safety_capability_unify",
            "admin_react_mvp",
            "quick_wins_pack",
        ):
            assert hasattr(feature_flags, f), f"feature_flags missing {f}"

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags
        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        # 24 mixins в MRO after T1.3.24
        for cls in ("Sprint5K2Flags", "Sprint19DXFlags", "Sprint19AIFlags"):
            assert cls in mro_names, f"{cls} missing в MRO"
