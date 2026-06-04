"""Unit tests for src.backend.core.config.features.billing (T1.3.11 split)."""

from __future__ import annotations

import os

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.billing import BillingFlags


class TestBillingFlagsClass:
    def test_billing_flags_importable(self) -> None:
        assert BillingFlags is not None

    def test_billing_flags_instantiates(self) -> None:
        flags = BillingFlags()
        for f in (
            "per_tenant_billing_enabled",
            "supply_chain_finale_strict",
            "openfeature_flagsmith_backend",
            "extensions_core_entities",
        ):
            assert getattr(flags, f) is False, f"{f} default не False"

    def test_billing_env_vars(self) -> None:
        os.environ["FEATURE_PER_TENANT_BILLING_ENABLED"] = "true"
        os.environ["FEATURE_OPENFEATURE_FLAGSMITH_BACKEND"] = "true"
        try:
            flags = BillingFlags()
            assert flags.per_tenant_billing_enabled is True
            assert flags.openfeature_flagsmith_backend is True
        finally:
            del os.environ["FEATURE_PER_TENANT_BILLING_ENABLED"]
            del os.environ["FEATURE_OPENFEATURE_FLAGSMITH_BACKEND"]

    def test_billing_field_count(self) -> None:
        fields = BillingFlags.model_fields
        names = list(fields.keys())
        # 4 fields: 3 Sprint 7 K1 per-tenant + 1 K9
        assert len(names) == 4


class TestBillingFlagsComposition:
    def test_feature_flags_inherits_billing_fields(self) -> None:
        for f in (
            "per_tenant_billing_enabled",
            "supply_chain_finale_strict",
            "openfeature_flagsmith_backend",
            "extensions_core_entities",
        ):
            assert hasattr(feature_flags, f), f"feature_flags missing {f}"

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags

        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        # 10 mixins в MRO
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
        ):
            assert cls in mro_names, f"{cls} missing в MRO"
