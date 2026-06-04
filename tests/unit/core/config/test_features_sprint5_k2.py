"""Unit tests for src.backend.core.config.features.sprint5_k2 (T1.3.22 split)."""

from __future__ import annotations

import os

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.sprint5_k2 import Sprint5K2Flags

# 5 fields total, all Sprint 5 K2 Resilience+Perf:
#   inbox_fail_closed (W3)
#   tenacity_finalized (W6)
#   per_tenant_rate_limit (W7)
#   graylog_chain_enabled (W5)
#   genai_chain_enabled (W5)
SPRINT5_K2_FIELD_NAMES = (
    "inbox_fail_closed",
    "tenacity_finalized",
    "per_tenant_rate_limit",
    "graylog_chain_enabled",
    "genai_chain_enabled",
)
EXPECTED_SPRINT5_K2_FIELD_COUNT = 5


class TestSprint5K2FlagsClass:
    def test_sprint5_k2_flags_importable(self) -> None:
        assert Sprint5K2Flags is not None

    def test_sprint5_k2_flags_instantiates(self) -> None:
        flags = Sprint5K2Flags()
        for f in SPRINT5_K2_FIELD_NAMES:
            assert getattr(flags, f) is False, f"{f} default не False"

    def test_sprint5_k2_env_vars(self) -> None:
        os.environ["FEATURE_INBOX_FAIL_CLOSED"] = "true"
        os.environ["FEATURE_GRAYLOG_CHAIN_ENABLED"] = "true"
        try:
            flags = Sprint5K2Flags()
            assert flags.inbox_fail_closed is True
            assert flags.graylog_chain_enabled is True
        finally:
            del os.environ["FEATURE_INBOX_FAIL_CLOSED"]
            del os.environ["FEATURE_GRAYLOG_CHAIN_ENABLED"]

    def test_sprint5_k2_field_count(self) -> None:
        fields = Sprint5K2Flags.model_fields
        names = list(fields.keys())
        # 5 fields
        assert len(names) == EXPECTED_SPRINT5_K2_FIELD_COUNT
        assert tuple(names) == SPRINT5_K2_FIELD_NAMES


class TestSprint5K2FlagsComposition:
    def test_feature_flags_inherits_sprint5_k2_fields(self) -> None:
        for f in SPRINT5_K2_FIELD_NAMES:
            assert hasattr(feature_flags, f), f"feature_flags missing {f}"

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags

        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        # Sprint5K2Flags must be in MRO (T1.3.22)
        assert "Sprint5K2Flags" in mro_names, "Sprint5K2Flags missing в MRO"
        # Sanity: должна стоять между Sprint5Flags и Sprint5DSLFlags
        assert (
            mro_names.index("Sprint5Flags")
            < mro_names.index("Sprint5K2Flags")
            < mro_names.index("Sprint5DSLFlags")
        )
