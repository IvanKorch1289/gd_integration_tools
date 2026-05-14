# ruff: noqa: S101
"""Тест feature_flag.credit_pipeline_v2 (default-OFF) — Sprint 7 Team T3.

Wave: ``[wave:s7/team-03-credit-1st-client]``.

DoD: feature_flag.credit_pipeline_v2 default-OFF; миграция legacy→V11
не активируется без явного flip.
"""

from __future__ import annotations

from src.backend.core.config.features import feature_flags


def test_credit_pipeline_v2_flag_exists_and_default_off() -> None:
    """Flag зарегистрирован и default ``False``."""
    assert hasattr(feature_flags, "credit_pipeline_v2")
    assert feature_flags.credit_pipeline_v2 is False
