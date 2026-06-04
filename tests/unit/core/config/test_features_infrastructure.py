"""Unit tests for src.backend.core.config.features.infrastructure (T1.3.17 split).

Subagent #2 (Sprint 5 K4+K5 + Sprint 8+9+10) created infrastructure.py
но timeout prevented test file creation. Orchestrator завершил.
"""

from __future__ import annotations

import os

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.infrastructure import InfrastructureFlags


class TestInfrastructureFlagsClass:
    def test_infrastructure_flags_importable(self) -> None:
        assert InfrastructureFlags is not None

    def test_infrastructure_flags_instantiates(self) -> None:
        flags = InfrastructureFlags()
        expected = [
            "rag_cache_l3_retrieval_invalidation",
            "multipart_rag_ingest",
            "multimodal_rag_docling",
            "langgraph_postgres_checkpoint",
            "dsl_expose_mcp",
            "rlm_hierarchical_memory",
            "unmask_pii_enabled",
            "mem0ai_enabled",
            "langfuse_mcp_prompt",
            "frontend_workflow_logs_page",
            "rpa_ocr_enabled",
            "cdc_enabled",
            "compression_brotli",
            "dsl_complexity_check_blocking",
            "mock_llm_enabled",
            "dsl_jinja_macros",
            "dsl_step_trace",
            "rule_engine_hot_reload",
            "http3_enabled",
            "route_loader_hot_reload",
            "streamlit_page_renumber",
            "hitl_panel_enabled",
            "tenant_token_budget_enabled",
            "saml_sp_initiated_enabled",
            "lazy_processor_loading",
            "clickhouse_bulk_writer_enabled",
        ]
        for f in expected:
            assert getattr(flags, f) is False, f"{f} default не False"

    def test_infrastructure_env_vars(self) -> None:
        os.environ["FEATURE_MEM0AI_ENABLED"] = "true"
        os.environ["FEATURE_HTTP3_ENABLED"] = "true"
        try:
            flags = InfrastructureFlags()
            assert flags.mem0ai_enabled is True
            assert flags.http3_enabled is True
        finally:
            del os.environ["FEATURE_MEM0AI_ENABLED"]
            del os.environ["FEATURE_HTTP3_ENABLED"]

    def test_infrastructure_field_count(self) -> None:
        fields = InfrastructureFlags.model_fields
        names = list(fields.keys())
        # 26 fields (Sprint 5 K4+K5 + Sprint 8+9+10)
        assert len(names) == 26


class TestInfrastructureFlagsComposition:
    def test_feature_flags_inherits_infrastructure_fields(self) -> None:
        for f in (
            "mem0ai_enabled",
            "langfuse_mcp_prompt",
            "rule_engine_hot_reload",
            "http3_enabled",
            "hitl_panel_enabled",
            "clickhouse_bulk_writer_enabled",
        ):
            assert hasattr(feature_flags, f), f"feature_flags missing {f}"

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags
        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        # 18 mixins в MRO (was 15, +3 from this batch)
        for cls in ("Sprint5DSLFlags", "InfrastructureFlags", "AIRAGFlags"):
            assert cls in mro_names, f"{cls} missing в MRO"
