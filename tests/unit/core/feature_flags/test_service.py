"""Tests for src.backend.core.feature_flags.service (Sprint 41)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from src.backend.core.feature_flags.runtime_overrides import reset_runtime_overrides
from src.backend.core.feature_flags.service import (
    FeatureFlagService,
    get_feature_flag_service,
)


@pytest.fixture(autouse=True)
def _reset_runtime_overrides() -> Iterator[None]:
    """Сбрасывает process-global singleton runtime-overrides до и после теста.

    Без сброса override'ы из одного теста утекали в следующие тесты этого
    файла и в другие файлы того же воркера — order-dependent падения.
    """
    reset_runtime_overrides()
    yield
    reset_runtime_overrides()


@pytest.fixture
def svc() -> FeatureFlagService:
    """Свежий ``FeatureFlagService`` для изоляции."""
    return FeatureFlagService()


class _FlagsStub:
    """Заглушка статического реестра feature-flags."""

    def __init__(self, **flags: Any) -> None:
        for name, value in flags.items():
            setattr(self, name, value)


def test_is_enabled_falls_back_to_static_registry(svc: FeatureFlagService) -> None:
    """Без override возвращается значение из static registry."""
    # Известный default-OFF флаг из реестра
    result = svc.is_enabled("openfeature_external")
    # S121 W1: default=False per D-AUDIT-FIX-184-2 (code matches doc).
    assert result is False  # default=False per experimental.py:79


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


def test_static_registry_replaced_after_import_is_visible(
    svc: FeatureFlagService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Подмена реестра после импорта видна сервису (регресс P1-3, волна 34/35).

    Сервис не должен кэшировать объект ``feature_flags`` на этапе импорта:
    автофикстуры подменяют атрибут
    ``src.backend.core.config.features.feature_flags`` уже после импорта
    модуля — раньше сервис продолжал читать старый объект и давал
    order-dependent падения (11 шт. в волне 34/35).
    """
    import src.backend.core.config.features as features_mod

    monkeypatch.setattr(features_mod, "feature_flags", _FlagsStub(dynamic_flag=True))

    assert svc.is_enabled("dynamic_flag") is True
    assert svc.get_int("dynamic_flag") == 1


def test_singleton_service_sees_replaced_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Process-wide singleton сервиса тоже видит подменённый реестр."""
    import src.backend.core.config.features as features_mod

    service = get_feature_flag_service()
    monkeypatch.setattr(features_mod, "feature_flags", _FlagsStub(dynamic_flag=True))

    assert service.is_enabled("dynamic_flag") is True


def test_service_created_during_replacement_reads_restored_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сервис, созданный в окне подмены, после её снятия читает актуальный реестр.

    Корневой сценарий дефекта: ``service.py`` импортировал ``feature_flags``
    на уровне модуля, поэтому сервис, созданный в окне подмены (первое
    обращение к singleton'у пришлось на чужую автофикстуру), навсегда
    оставался привязан к заглушке.
    """
    import src.backend.core.config.features as features_mod

    original = features_mod.feature_flags
    monkeypatch.setattr(features_mod, "feature_flags", _FlagsStub(dynamic_flag=True))
    service = FeatureFlagService()  # создан в окне подмены
    assert service.is_enabled("dynamic_flag") is True

    monkeypatch.setattr(features_mod, "feature_flags", original)
    assert service.is_enabled("dynamic_flag") is False


def test_replaced_registry_keeps_override_priority(
    svc: FeatureFlagService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Приоритет runtime override > static > default не изменился."""
    import src.backend.core.config.features as features_mod

    monkeypatch.setattr(features_mod, "feature_flags", _FlagsStub(dynamic_flag=False))

    # Static registry (подменённая) важнее default.
    assert svc.is_enabled("dynamic_flag") is False
    assert svc.is_enabled("dynamic_flag", default=True) is False
    # Runtime override важнее static registry.
    svc._overrides.set("dynamic_flag", True)
    assert svc.is_enabled("dynamic_flag") is True
    # Per-tenant override важнее global override.
    svc._overrides.set("dynamic_flag", False, tenant_id="acme")
    assert svc.is_enabled("dynamic_flag", tenant_id="acme") is False
    assert svc.is_enabled("dynamic_flag") is True
    # Неизвестный флаг → default.
    assert svc.is_enabled("definitely_unknown_flag_xyz", default=True) is True
