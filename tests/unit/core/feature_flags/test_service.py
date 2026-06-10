"""Tests for src.backend.core.feature_flags.service (Sprint 41)."""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.core.feature_flags.service import FeatureFlagService


@pytest.fixture
def svc() -> FeatureFlagService:
    """Свежий ``FeatureFlagService`` для изоляции."""
    return FeatureFlagService()


def test_is_enabled_falls_back_to_static_registry(svc: FeatureFlagService) -> None:
    """Без override возвращается значение из static registry."""
    # Известный default-OFF флаг из реестра
    result = svc.is_enabled("openfeature_external")
    assert result is False


def test_is_enabled_respects_runtime_override(svc: FeatureFlagService) -> None:
    """Runtime override имеет приоритет над static registry."""
    svc._overrides.set("openfeature_external", True)
    result = svc.is_enabled("openfeature_external")
    assert result is True


def test_is_enabled_returns_default_for_unknown_flag(svc: FeatureFlagService) -> None:
    """Для неизвестного флага возвращается default."""
    assert svc.is_enabled("definitely_unknown_flag_xyz") is False
    assert svc.is_enabled("definitely_unknown_flag_xyz", default=True) is True


def test_get_string_returns_override(svc: FeatureFlagService) -> None:
    """String-lookup учитывает override."""
    svc._overrides.set("any_flag", "overridden")
    result = svc.get_string("any_flag")
    assert result == "overridden"


def test_get_int_coerces_override(svc: FeatureFlagService) -> None:
    """Int-lookup приводит override к int."""
    svc._overrides.set("any_flag", "42")
    result = svc.get_int("any_flag")
    assert result == 42


def test_get_int_falls_back_to_default_on_bad_value(svc: FeatureFlagService) -> None:
    """Невалидное значение override → default."""
    svc._overrides.set("any_flag", "not-a-number")
    result = svc.get_int("any_flag", default=7)
    assert result == 7
