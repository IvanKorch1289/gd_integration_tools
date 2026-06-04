"""Unit tests for src.backend.core.config.features.sprint5 (T1.3.12 split)."""

from __future__ import annotations

import os

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.sprint5 import Sprint5Flags


class TestSprint5FlagsClass:
    def test_sprint5_flags_importable(self) -> None:
        assert Sprint5Flags is not None

    def test_sprint5_flags_instantiates(self) -> None:
        flags = Sprint5Flags()
        for f in (
            "supply_chain_ci_gate",
            "dlq_replay_rbac",
            "inbox_audit_pii_mask",
            "dlq_unified_enabled",
        ):
            assert getattr(flags, f) is False, f"{f} default не False"

    def test_sprint5_env_vars(self) -> None:
        os.environ["FEATURE_SUPPLY_CHAIN_CI_GATE"] = "true"
        os.environ["FEATURE_DLQ_REPLAY_RBAC"] = "true"
        try:
            flags = Sprint5Flags()
            assert flags.supply_chain_ci_gate is True
            assert flags.dlq_replay_rbac is True
        finally:
            del os.environ["FEATURE_SUPPLY_CHAIN_CI_GATE"]
            del os.environ["FEATURE_DLQ_REPLAY_RBAC"]

    def test_sprint5_field_count(self) -> None:
        fields = Sprint5Flags.model_fields
        names = list(fields.keys())
        # 4 fields: 3 Sprint 5 K1 + 1 Sprint 5 K2
        assert len(names) == 4


class TestSprint5FlagsComposition:
    def test_feature_flags_inherits_sprint5_fields(self) -> None:
        for f in (
            "supply_chain_ci_gate",
            "dlq_replay_rbac",
            "inbox_audit_pii_mask",
            "dlq_unified_enabled",
        ):
            assert hasattr(feature_flags, f), f"feature_flags missing {f}"

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags

        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        # 11 mixins в MRO
        for cls in (
            "AuthFlags",
            "SecurityFlags",
            "ObservabilityFlags",
            "NetFlags",
            "WorkflowFlags",
            "AIFlags",
            "DSLFlags",
            "ExperimentalFlags",
            "ResilienceFlags",
            "BillingFlags",
            "Sprint5Flags",
        ):
            assert cls in mro_names, f"{cls} missing в MRO"
