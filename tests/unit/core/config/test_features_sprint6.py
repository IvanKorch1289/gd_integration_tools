"""Unit tests for src.backend.core.config.features.sprint6 (T1.3.14 split)."""

from __future__ import annotations

import os

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.sprint6 import Sprint6Flags

# 21 fields total, distributed across 5 K-domains (Sprint 6):
#   K1 Security: 6
#   K2 Resilience+Perf: 7
#   K3 DSL+Workflow: 2
#   K4 AI+Quality: 3
#   K5 Frontend+Chaos: 3
SPRINT6_FIELD_NAMES = (
    # K1 Security (6)
    "saml_ad_login_enabled",
    "outbound_metering_strict",
    "supply_chain_strict_mode",
    "owasp_zap_gate_enabled",
    "custom_code_audit_enabled",
    "codeclone_fail_on_new",
    # K2 Resilience+Perf (7)
    "perf_gate_strict",
    "structlog_batching_enabled",
    "processor_health_checks_strict",
    "backpressure_streaming_enabled",
    "granian_rsgi_mode_enabled",
    "schemathesis_gate_enabled",
    "service_doc_gate_enabled",
    # K3 DSL+Workflow (2)
    "com_sidecar_enabled",
    "dsl_linter_strict",
    # K4 AI+Quality (3)
    "inspect_ai_eval_enabled",
    "dspy_eval_pipeline_enabled",
    "ai_cost_dashboard_strict",
    # K5 Frontend+Chaos (3)
    "chaos_tests_blocking",
    "resilience_dashboard_enabled",
    "pool_monitor_enabled",
)
EXPECTED_SPRINT6_FIELD_COUNT = 21


class TestSprint6FlagsClass:
    def test_sprint6_flags_importable(self) -> None:
        assert Sprint6Flags is not None

    def test_sprint6_flags_instantiates(self) -> None:
        flags = Sprint6Flags()
        for f in SPRINT6_FIELD_NAMES:
            assert getattr(flags, f) is False, f"{f} default не False"

    def test_sprint6_env_vars(self) -> None:
        os.environ["FEATURE_SAML_AD_LOGIN_ENABLED"] = "true"
        os.environ["FEATURE_PERF_GATE_STRICT"] = "true"
        os.environ["FEATURE_CHAOS_TESTS_BLOCKING"] = "true"
        try:
            flags = Sprint6Flags()
            assert flags.saml_ad_login_enabled is True
            assert flags.perf_gate_strict is True
            assert flags.chaos_tests_blocking is True
        finally:
            del os.environ["FEATURE_SAML_AD_LOGIN_ENABLED"]
            del os.environ["FEATURE_PERF_GATE_STRICT"]
            del os.environ["FEATURE_CHAOS_TESTS_BLOCKING"]

    def test_sprint6_field_count(self) -> None:
        fields = Sprint6Flags.model_fields
        names = list(fields.keys())
        # 21 fields: 6 K1 + 7 K2 + 2 K3 + 3 K4 + 3 K5
        assert len(names) == EXPECTED_SPRINT6_FIELD_COUNT
        assert tuple(names) == SPRINT6_FIELD_NAMES


class TestSprint6FlagsComposition:
    def test_feature_flags_inherits_sprint6_fields(self) -> None:
        for f in SPRINT6_FIELD_NAMES:
            assert hasattr(feature_flags, f), f"feature_flags missing {f}"

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags
        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        # 12 mixins в MRO (после T1.3.13 plugins + T1.3.14 sprint6)
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
            "Sprint6Flags",
        ):
            assert cls in mro_names, f"{cls} missing в MRO"
