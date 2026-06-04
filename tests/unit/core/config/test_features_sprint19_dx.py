"""Unit tests for src.backend.core.config.features.sprint19_dx (T1.3.23 split)."""

from __future__ import annotations

import os

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.sprint19_dx import Sprint19DXFlags

# 12 fields total, first half of Sprint 19 (DSL+DX themes: routes, AI/RAG, LSP/IDE):
#   K3 DSL/Workflow: 3
#   K4 AI/RAG: 5
#   K5 RPA/DX: 4
SPRINT19_DX_FIELD_NAMES = (
    # K3 DSL/Workflow (3)
    "workflow_versioning_routes",
    "route_composition_include",
    "route_authz_requires_permission",
    # K4 AI/RAG (5)
    "rag_multipart_ingest",
    "reranking_pipeline_enabled",
    "banking_ai_processors_impl",
    "banking_ai_processors_enabled",
    "langmem_consolidation_impl",
    # K5 RPA/DX (4)
    "rpa_session_persistence",
    "vscode_extension_published",
    "lsp_server_strict",
    "testkit_public_api",
)
EXPECTED_SPRINT19_DX_FIELD_COUNT = 12


class TestSprint19DXFlagsClass:
    def test_sprint19_dx_flags_importable(self) -> None:
        assert Sprint19DXFlags is not None

    def test_sprint19_dx_flags_instantiates(self) -> None:
        flags = Sprint19DXFlags()
        for f in SPRINT19_DX_FIELD_NAMES:
            assert getattr(flags, f) is False, f"{f} default не False"

    def test_sprint19_dx_env_vars(self) -> None:
        os.environ["FEATURE_WORKFLOW_VERSIONING_ROUTES"] = "true"
        os.environ["FEATURE_RAG_MULTIPART_INGEST"] = "true"
        os.environ["FEATURE_TESTKIT_PUBLIC_API"] = "true"
        try:
            flags = Sprint19DXFlags()
            assert flags.workflow_versioning_routes is True
            assert flags.rag_multipart_ingest is True
            assert flags.testkit_public_api is True
        finally:
            del os.environ["FEATURE_WORKFLOW_VERSIONING_ROUTES"]
            del os.environ["FEATURE_RAG_MULTIPART_INGEST"]
            del os.environ["FEATURE_TESTKIT_PUBLIC_API"]

    def test_sprint19_dx_field_count(self) -> None:
        fields = Sprint19DXFlags.model_fields
        names = list(fields.keys())
        # 12 fields: K3 DSL/Workflow (3) + K4 AI/RAG (5) + K5 RPA/DX (4)
        assert len(names) == EXPECTED_SPRINT19_DX_FIELD_COUNT, (
            f"expected {EXPECTED_SPRINT19_DX_FIELD_COUNT}, got {len(names)}: {names}"
        )
        # Verify all expected names are present (order independent)
        for name in SPRINT19_DX_FIELD_NAMES:
            assert name in names, f"{name} missing from Sprint19DXFlags"


class TestSprint19DXFlagsComposition:
    def test_feature_flags_inherits_sprint19_dx_fields(self) -> None:
        for f in SPRINT19_DX_FIELD_NAMES:
            assert hasattr(feature_flags, f), f"feature_flags missing {f}"

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags
        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        # Sprint19DXFlags must be in MRO alongside its parallel siblings
        # (sprint5_k2, sprint19_ai) and earlier splits.
        for cls in (
            "Sprint19DXFlags",
            "Sprint19AIFlags",  # parallel split, second half
            "Sprint5K2Flags",  # parallel split, also modifies __init__.py
            "Sprint5Flags",
            "Sprint5DSLFlags",
            "Sprint6Flags",
            "Sprint7Flags",
            "Sprints1517Flags",
            "Sprints1821Flags",
            "Sprints2427Flags",
        ):
            assert cls in mro_names, f"{cls} missing в MRO"
