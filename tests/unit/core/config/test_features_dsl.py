"""Unit tests for src.backend.core.config.features.dsl (T1.3.8 split)."""

from __future__ import annotations

import os

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.dsl import DSLFlags


class TestDSLFlagsClass:
    def test_dsl_flags_importable(self) -> None:
        assert DSLFlags is not None

    def test_dsl_flags_instantiates(self) -> None:
        flags = DSLFlags()
        for f in (
            "frontend_schema_registry_ui",
            "frontend_action_bus_ui",
            "dsl_processor_registry_strict",
            "dsl_route_hot_reload",
            "lsp_server_published",
            "admin_marketplace_endpoints",
            "dsl_visual_editor_enabled",
            "builder_source_sugar",
            "service_toml_loader",
            "graphql_subscription_source",
            "email_imap_source",
            "notification_dsl_enabled",
        ):
            assert getattr(flags, f) is False, f"{f} default не False"

    def test_dsl_env_vars(self) -> None:
        os.environ["FEATURE_DSL_ROUTE_HOT_RELOAD"] = "true"
        os.environ["FEATURE_BUILDER_SOURCE_SUGAR"] = "true"
        try:
            flags = DSLFlags()
            assert flags.dsl_route_hot_reload is True
            assert flags.builder_source_sugar is True
        finally:
            del os.environ["FEATURE_DSL_ROUTE_HOT_RELOAD"]
            del os.environ["FEATURE_BUILDER_SOURCE_SUGAR"]

    def test_dsl_field_count(self) -> None:
        fields = DSLFlags.model_fields
        names = list(fields.keys())
        # 12 K5 DSL + K3 sources fields
        assert len(names) == 12


class TestDSLFlagsComposition:
    def test_feature_flags_inherits_dsl_fields(self) -> None:
        for f in (
            "frontend_schema_registry_ui",
            "admin_marketplace_endpoints",
            "dsl_visual_editor_enabled",
            "builder_source_sugar",
            "graphql_subscription_source",
            "email_imap_source",
            "notification_dsl_enabled",
        ):
            assert hasattr(feature_flags, f), f"feature_flags missing {f}"

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags
        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        # 7 mixins в MRO
        for cls in ("AuthFlags", "SecurityFlags", "ObservabilityFlags",
                    "NetFlags", "WorkflowFlags", "AIFlags", "DSLFlags"):
            assert cls in mro_names, f"{cls} missing в MRO"
