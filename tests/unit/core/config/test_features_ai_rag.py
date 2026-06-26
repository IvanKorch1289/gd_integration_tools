"""Unit tests for src.backend.core.config.features.ai_rag (T1.3.18 split)."""

from __future__ import annotations

import os

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.ai_rag import AIRAGFlags

# 29 fields total (S38 T1.3.18):
#   Sprint 11 — AI/RAG Completion (11): 10 bool + 1 int
#   Sprint 12 — Workflow Enhancement (18): 18 bool
AIRAG_FIELD_NAMES = (
    # Sprint 11 — AI/RAG Completion (10 bool + 1 int)
    "rag_pii_retrieval_mask",
    "guardrails_per_tenant",
    "distributed_rl_redis_cluster",
    "multimodal_rag_full",
    "adaptive_rag_strategy",
    "langgraph_checkpoint_ui",
    "dspy_feedback_loop",
    "ai_model_registry_ui",
    "ai_route_optimization",
    "embedding_ab_migration",
    "embedding_v2_traffic",
    # Sprint 12 — Workflow Enhancement (18)
    "workflow_audit_extended",
    "workflow_mtls_enabled",
    "workflow_sla_dashboard_enabled",
    "workflow_worker_autoscale_enabled",
    "workflow_visual_diff_enabled",
    "workflow_cron_builder_enabled",
    "workflow_cost_estimation_enabled",
    "workflow_reactive_triggers_enabled",
    "workflow_template_library_enabled",
    "workflow_template_semantic_search",
    "workflow_saga_viewer_enabled",
    "workflow_cancel_dsl_enabled",
    "workflow_versioning_ui_enabled",
    "ai_workflow_examples_enabled",
    "ai_workflow_cost_estimation_enabled",
    "workflow_template_streamlit_enabled",
    "hitl_history_enabled",
    "workflow_cron_dashboard_enabled",
)
# Field name → expected default value
AIRAG_DEFAULT_TRUE = frozenset(
    {
        "workflow_audit_extended",
        "workflow_sla_dashboard_enabled",
        "workflow_visual_diff_enabled",
        "workflow_cron_builder_enabled",
        "workflow_cost_estimation_enabled",
        "workflow_template_library_enabled",
        "workflow_saga_viewer_enabled",
        "workflow_cancel_dsl_enabled",
        "workflow_versioning_ui_enabled",
        "ai_workflow_cost_estimation_enabled",
        "workflow_template_streamlit_enabled",
        "hitl_history_enabled",
        "workflow_cron_dashboard_enabled",
    }
)
AIRAG_INT_FIELDS = frozenset({"embedding_v2_traffic"})
EXPECTED_AIRAG_FIELD_COUNT = 29


class TestAIRAGFlagsClass:
    def test_ai_rag_flags_importable(self) -> None:
        assert AIRAGFlags is not None

    def test_ai_rag_flags_instantiates(self) -> None:
        flags = AIRAGFlags()
        for f in AIRAG_FIELD_NAMES:
            if f in AIRAG_INT_FIELDS:
                assert getattr(flags, f) == 0, f"{f} default не 0"
            elif f in AIRAG_DEFAULT_TRUE:
                assert getattr(flags, f) is True, f"{f} default не True"
            else:
                assert getattr(flags, f) is True, f"{f} default не False"

    def test_ai_rag_env_vars(self) -> None:
        os.environ["FEATURE_RAG_PII_RETRIEVAL_MASK"] = "true"
        os.environ["FEATURE_WORKFLOW_MTLS_ENABLED"] = "true"
        os.environ["FEATURE_EMBEDDING_V2_TRAFFIC"] = "75"
        try:
            flags = AIRAGFlags()
            assert flags.rag_pii_retrieval_mask is True
            assert flags.workflow_mtls_enabled is True
            assert flags.embedding_v2_traffic == 75
        finally:
            del os.environ["FEATURE_RAG_PII_RETRIEVAL_MASK"]
            del os.environ["FEATURE_WORKFLOW_MTLS_ENABLED"]
            del os.environ["FEATURE_EMBEDDING_V2_TRAFFIC"]

    def test_ai_rag_field_count(self) -> None:
        fields = AIRAGFlags.model_fields
        names = list(fields.keys())
        # 29 fields: 11 Sprint 11 (10 bool + 1 int) + 18 Sprint 12 bool
        assert len(names) == EXPECTED_AIRAG_FIELD_COUNT
        assert tuple(names) == AIRAG_FIELD_NAMES


class TestAIRAGFlagsComposition:
    def test_feature_flags_inherits_ai_rag_fields(self) -> None:
        for f in AIRAG_FIELD_NAMES:
            assert hasattr(feature_flags, f), f"feature_flags missing {f}"

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags

        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        # 17 mixins в MRO (после T1.3.17 infrastructure + T1.3.18 ai_rag)
        for cls in (
            "AuthFlags",
            "SecurityFlags",
            "ObservabilityFlags",
            "NetFlags",
            "PluginsFlags",
            "WorkflowFlags",
            "AIFlags",
            "AIRAGFlags",
            "DSLFlags",
            "ExperimentalFlags",
            "InfrastructureFlags",
            "ResilienceFlags",
            "BillingFlags",
            "Sprint5Flags",
            "Sprint5DSLFlags",
            "Sprint6Flags",
            "Sprint7Flags",
        ):
            assert cls in mro_names, f"{cls} missing в MRO"
