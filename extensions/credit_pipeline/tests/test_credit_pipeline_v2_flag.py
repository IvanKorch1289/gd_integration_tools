# ruff: noqa: S101
"""Тест feature_flag.credit_pipeline_v2 (default-OFF) — Sprint 7 Team T3.

Wave: ``[wave:s7/team-03-credit-1st-client]``.

DoD: feature_flag.credit_pipeline_v2 default-OFF; миграция legacy→V11
не активируется без явного flip.
"""

from __future__ import annotations

from src.backend.core.feature_flags import get_feature_flag_service


def test_credit_pipeline_v2_flag_exists_and_default_off() -> None:
    """Flag зарегистрирован и default ``False``."""
    assert get_feature_flag_service().is_enabled("credit_pipeline_v2") is False
