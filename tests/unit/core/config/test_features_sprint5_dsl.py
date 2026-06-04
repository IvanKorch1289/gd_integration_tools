"""Unit tests for src.backend.core.config.features.sprint5_dsl (T1.3.16 split)."""

from __future__ import annotations

import os

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.sprint5_dsl import Sprint5DSLFlags

# 25 fields total, Sprint 5 K3 DSL+Workflow (S38 T1.3.16):
SPRINT5_DSL_FIELD_NAMES = (
    # K3 DSL+Workflow W1 (4)
    "proc_html_template",
    "proc_jsonpath",
    "proc_jq",
    "proc_regex_extractor",
    # K3 DSL+Workflow W2 (3)
    "proc_webhook_signature",
    "proc_zip_archive",
    "proc_pdf_template",
    # K3 DSL+Workflow W3 (5)
    "proc_ldap_query",
    "proc_webdav",
    "proc_ics_calendar",
    "proc_unit_conversion",
    "proc_geo",
    # K3 DSL+Workflow W4 (1)
    "proc_rate_convert",
    # K3 DSL+Workflow W5-W14 (12)
    "db_call_procedure_enabled",
    "policy_chainable_enabled",
    "web_search_enabled",
    "workflow_step_log_enabled",
    "workflow_dryrun_enabled",
    "cdc_postgres_enabled",
    "result_unwrap_processor",
    "blueprint_cdc_enrich",
    "blueprint_ai_pipeline",
    "blueprint_saga_compensation",
    "taskgroup_processors",
    "invoke_workflow_reply_enabled",
)
EXPECTED_SPRINT5_DSL_FIELD_COUNT = 25


class TestSprint5DSLFlagsClass:
    def test_sprint5_dsl_flags_importable(self) -> None:
        assert Sprint5DSLFlags is not None

    def test_sprint5_dsl_flags_instantiates(self) -> None:
        flags = Sprint5DSLFlags()
        for f in SPRINT5_DSL_FIELD_NAMES:
            assert getattr(flags, f) is False, f"{f} default не False"

    def test_sprint5_dsl_env_vars(self) -> None:
        os.environ["FEATURE_PROC_HTML_TEMPLATE"] = "true"
        os.environ["FEATURE_DB_CALL_PROCEDURE_ENABLED"] = "true"
        os.environ["FEATURE_INVOKE_WORKFLOW_REPLY_ENABLED"] = "true"
        try:
            flags = Sprint5DSLFlags()
            assert flags.proc_html_template is True
            assert flags.db_call_procedure_enabled is True
            assert flags.invoke_workflow_reply_enabled is True
        finally:
            del os.environ["FEATURE_PROC_HTML_TEMPLATE"]
            del os.environ["FEATURE_DB_CALL_PROCEDURE_ENABLED"]
            del os.environ["FEATURE_INVOKE_WORKFLOW_REPLY_ENABLED"]

    def test_sprint5_dsl_field_count(self) -> None:
        fields = Sprint5DSLFlags.model_fields
        names = list(fields.keys())
        # 25 fields: Sprint 5 K3 DSL+Workflow
        assert len(names) == EXPECTED_SPRINT5_DSL_FIELD_COUNT
        assert tuple(names) == SPRINT5_DSL_FIELD_NAMES


class TestSprint5DSLFlagsComposition:
    def test_feature_flags_inherits_sprint5_dsl_fields(self) -> None:
        for f in SPRINT5_DSL_FIELD_NAMES:
            assert hasattr(feature_flags, f), f"feature_flags missing {f}"

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags

        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        # 15 mixins в MRO (после T1.3.16 sprint5_dsl)
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
            "Sprint5DSLFlags",
            "Sprint6Flags",
            "Sprint7Flags",
        ):
            assert cls in mro_names, f"{cls} missing в MRO"
