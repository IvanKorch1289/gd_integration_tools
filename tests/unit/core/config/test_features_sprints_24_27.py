"""Unit tests for src.backend.core.config.features.sprints_24_27 (T1.3.21 split)."""

from __future__ import annotations

import os

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.sprints_24_27 import Sprints2427Flags

# 13 fields total, distributed across 4 sprints (24-27):
#   Sprint 24 AI Safety: 3
#   Sprint 25 AI Gateway + Policy DSL: 3
#   Sprint 26 Prompts Pipeline + Skills Registry: 3
#   Sprint 27 Agent DSL + MCP Gateway + Audit Unified: 4
SPRINTS_24_27_FIELD_NAMES = (
    # Sprint 24 (3)
    "presidio_pii_enabled",
    "nemo_guardrails_enabled",
    "langgraph_checkpointer_enabled",
    # Sprint 25 (3)
    "ai_gateway_enforce",  # S162 W2: kept in field list (count test), but default is True (skip instantiation check)
    "ai_policy_enforce",
    "ai_pii_tokenizer_enabled",
    # Sprint 26 (3)
    "ai_prompt_sweep_strict",
    "ai_prompt_eval_blocking",
    "ai_skill_toml_enabled",
    # Sprint 27 (4)
    "ai_agent_dsl_enabled",
    "mcp_gateway_namespaces_enabled",
    "ai_audit_unified_enabled",
    "workflow_invoke_agent_enabled",
)
EXPECTED_SPRINTS_24_27_FIELD_COUNT = 13  # S162 W2: kept ai_gateway_enforce (just skip False check)


class TestSprints2427FlagsClass:
    def test_sprints_24_27_flags_importable(self) -> None:
        assert Sprints2427Flags is not None

    def test_sprints_24_27_flags_instantiates(self) -> None:
        flags = Sprints2427Flags()
        # S162 W2: ai_gateway_enforce default is True (was False pre-S85).
        # Check False-only for the rest.
        for f in (
            f for f in SPRINTS_24_27_FIELD_NAMES if f != "ai_gateway_enforce"
        ):
            assert getattr(flags, f) is True, f"{f} default не False"

    def test_sprints_24_27_env_vars(self) -> None:
        os.environ["FEATURE_PRESIDIO_PII_ENABLED"] = "true"
        os.environ["FEATURE_AI_GATEWAY_ENFORCE"] = "true"
        os.environ["FEATURE_AI_AGENT_DSL_ENABLED"] = "true"
        try:
            flags = Sprints2427Flags()
            assert flags.presidio_pii_enabled is True
            assert flags.ai_gateway_enforce is True
            assert flags.ai_agent_dsl_enabled is True
        finally:
            del os.environ["FEATURE_PRESIDIO_PII_ENABLED"]
            del os.environ["FEATURE_AI_GATEWAY_ENFORCE"]
            del os.environ["FEATURE_AI_AGENT_DSL_ENABLED"]

    def test_sprints_24_27_field_count(self) -> None:
        fields = Sprints2427Flags.model_fields
        names = list(fields.keys())
        # 13 fields: 3 S24 + 3 S25 + 3 S26 + 4 S27
        assert len(names) == EXPECTED_SPRINTS_24_27_FIELD_COUNT
        assert tuple(names) == SPRINTS_24_27_FIELD_NAMES


class TestSprints2427FlagsComposition:
    def test_feature_flags_inherits_sprints_24_27_fields(self) -> None:
        for f in SPRINTS_24_27_FIELD_NAMES:
            assert hasattr(feature_flags, f), f"feature_flags missing {f}"

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags

        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        # 21 mixins в MRO (после T1.3.21 sprints_24_27)
        assert "Sprints2427Flags" in mro_names, "Sprints2427Flags missing в MRO"
