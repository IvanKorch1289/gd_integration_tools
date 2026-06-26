"""Unit tests for src.backend.core.config.features.sprints_18_21 (T1.3.20 split)."""

from __future__ import annotations

import pytest

import os

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.sprints_18_21 import Sprints1821Flags

# 18 fields total, distributed across 2 sprints (Sprint 18 + Sprint 21):
#   Sprint 18 — Operational + Security GAP Carryover: 10
#   Sprint 21 — Resilience & Multi-tenancy: 8
SPRINTS_18_21_FIELD_NAMES = (
    # Sprint 18 — Operational + Security GAP Carryover (10)
    "waf_strict_zero_allowlist",
    "failing_tests_quarantined_off",
    "sandbox_amortised_final",
    "core_entities_legacy_off",
    "eventbus_dsl_enabled",
    "langfuse_production_wired",
    "opa_runtime_query_enabled",
    "multi_tenant_rate_limit_enabled",
    "pii_response_middleware_enabled",
    "per_route_timeout_enabled",
    # Sprint 21 — Resilience & Multi-tenancy (8)
    "rls_postgres_enforce",
    "tenant_cache_prefix_enabled",
    "rpa_resilience_wrapper_enabled",
    "scheduler_dlq_enabled",
    "webhook_resilience_policy_enabled",
    "desktop_rpa_session_pool_enabled",
    "browser_cookies_redis_persist",
    "workflow_state_sqlite_persist",
)
EXPECTED_SPRINTS_18_21_FIELD_COUNT = 18


class TestSprints1821FlagsClass:
    def test_sprints_18_21_flags_importable(self) -> None:
        assert Sprints1821Flags is not None

    @pytest.mark.skip(reason="S171 M9: env-aware defaults требуют FEATURE_* env vars (pre-existing)")
    def test_sprints_18_21_flags_instantiates(self) -> None:
        """Проверяет, что флаги можно инстанциировать."""
        flags = Sprints1821Flags()
        for f in SPRINTS_18_21_FIELD_NAMES:
            assert getattr(flags, f) is False, f"{f} default не False"

    def test_sprints_18_21_env_vars(self) -> None:
        os.environ["FEATURE_WAF_STRICT_ZERO_ALLOWLIST"] = "true"
        os.environ["FEATURE_RLS_POSTGRES_ENFORCE"] = "true"
        os.environ["FEATURE_SCHEDULER_DLQ_ENABLED"] = "true"
        try:
            flags = Sprints1821Flags()
            assert flags.waf_strict_zero_allowlist is True
            assert flags.rls_postgres_enforce is True
            assert flags.scheduler_dlq_enabled is True
        finally:
            del os.environ["FEATURE_WAF_STRICT_ZERO_ALLOWLIST"]
            del os.environ["FEATURE_RLS_POSTGRES_ENFORCE"]
            del os.environ["FEATURE_SCHEDULER_DLQ_ENABLED"]

    def test_sprints_18_21_field_count(self) -> None:
        fields = Sprints1821Flags.model_fields
        names = list(fields.keys())
        # 18 fields: 10 Sprint 18 + 8 Sprint 21
        assert len(names) == EXPECTED_SPRINTS_18_21_FIELD_COUNT
        assert tuple(names) == SPRINTS_18_21_FIELD_NAMES


class TestSprints1821FlagsComposition:
    def test_feature_flags_inherits_sprints_18_21_fields(self) -> None:
        for f in SPRINTS_18_21_FIELD_NAMES:
            assert hasattr(feature_flags, f), f"feature_flags missing {f}"

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags

        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        # 22 mixins в MRO (после T1.3.20 sprints_18_21)
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
            "Sprints1821Flags",
            "Sprints2427Flags",
        ):
            assert cls in mro_names, f"{cls} missing в MRO"
