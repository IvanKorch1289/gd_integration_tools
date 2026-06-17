"""Unit tests for src.backend.core.config.features.ai (T1.3.7 split)."""

from __future__ import annotations

import os

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.ai import AIFlags


class TestAIFlagsClass:
    def test_ai_flags_importable(self) -> None:
        assert AIFlags is not None

    def test_ai_flags_instantiates(self) -> None:
        flags = AIFlags()
        # Defaults — все False
        for f in (
            "search_provider_searxng",
            "langmem_enabled",
            "mcp_tools_input_schema_strict",
            "langfuse_v3",
            # "rag_cache_l2_semantic",  # S162 W2: default changed to True
            "rag_cache_l3_retrieval",
            "ai_workspace_ttl_cleanup",
            "prompt_registry_langfuse",
            "multimodal_rag_enabled",
        ):
            assert getattr(flags, f) is False, f"{f} default не False"

    def test_ai_env_vars(self) -> None:
        os.environ["FEATURE_LANGFUSE_V3"] = "true"
        os.environ["FEATURE_RAG_CACHE_L2_SEMANTIC"] = "true"
        try:
            flags = AIFlags()
            assert flags.langfuse_v3 is True
            assert flags.rag_cache_l2_semantic is True
        finally:
            del os.environ["FEATURE_LANGFUSE_V3"]
            del os.environ["FEATURE_RAG_CACHE_L2_SEMANTIC"]

    def test_ai_field_count(self) -> None:
        fields = AIFlags.model_fields
        names = list(fields.keys())
        # S162 W2: was 9, sibling Sprint 1 added a field (now 10).
        assert len(names) == 10
        assert "search_provider_searxng" in names
        assert "multimodal_rag_enabled" in names


class TestAIFlagsComposition:
    def test_feature_flags_inherits_ai_fields(self) -> None:
        for f in (
            "search_provider_searxng",
            "langmem_enabled",
            "mcp_tools_input_schema_strict",
            "langfuse_v3",
            "rag_cache_l2_semantic",
            "rag_cache_l3_retrieval",
            "ai_workspace_ttl_cleanup",
            "prompt_registry_langfuse",
            "multimodal_rag_enabled",
        ):
            assert hasattr(feature_flags, f), f"feature_flags missing {f}"

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags

        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        # 6 mixins в MRO
        for cls in (
            "AuthFlags",
            "SecurityFlags",
            "ObservabilityFlags",
            "NetFlags",
            "WorkflowFlags",
            "AIFlags",
        ):
            assert cls in mro_names, f"{cls} missing в MRO"
