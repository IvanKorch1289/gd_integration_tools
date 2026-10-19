"""Tests for ``src.backend.services.ai.guardrails.tenant_config``.

Sprint 11 K1 W2, S172 NeMo migration: per-tenant guardrails config
с поддержкой legacy ``rebuff`` provider.
"""

from __future__ import annotations

from src.backend.services.ai.guardrails import tenant_config as mod
from src.backend.services.ai.guardrails.tenant_config import (
    GuardrailsConfig,
    GuardrailsThresholds,
    _DEFAULT,
    get_default_config,
)


class TestGuardrailsThresholdsDefaults:
    """Дефолтные пороги."""

    def test_default_lakera_threshold(self) -> None:
        t = GuardrailsThresholds()
        assert t.lakera_threshold == 0.5

    def test_default_rebuff_threshold(self) -> None:
        # legacy S172 — но default сохранён
        t = GuardrailsThresholds()
        assert t.rebuff_threshold == 0.7


class TestGuardrailsThresholdsExplicit:
    """Явная инициализация порогов."""

    def test_custom_lakera(self) -> None:
        t = GuardrailsThresholds(lakera_threshold=0.95)
        assert t.lakera_threshold == 0.95

    def test_custom_rebuff(self) -> None:
        t = GuardrailsThresholds(rebuff_threshold=0.1)
        assert t.rebuff_threshold == 0.1

    def test_zero_threshold(self) -> None:
        # 0.0 — допустимо (блокировать всё)
        t = GuardrailsThresholds(lakera_threshold=0.0)
        assert t.lakera_threshold == 0.0

    def test_one_threshold(self) -> None:
        # 1.0 — допустимо (фактически отключить)
        t = GuardrailsThresholds(lakera_threshold=1.0)
        assert t.lakera_threshold == 1.0


class TestGuardrailsThresholdsFrozen:
    """frozen=True — атрибуты неизменяемы после создания."""

    def test_immutable_after_creation(self) -> None:
        import dataclasses

        t = GuardrailsThresholds()
        with __import__("dataclasses").FrozenInstanceError if False else __import__(
            "pytest"
        ).raises(dataclasses.FrozenInstanceError):
            t.lakera_threshold = 0.9  # type: ignore[misc]


class TestGuardrailsConfigDefaults:
    """Дефолты для полного конфига."""

    def test_default_enabled_providers(self) -> None:
        cfg = GuardrailsConfig()
        # Default — frozenset({"lakera", "nemo"})
        assert cfg.enabled_providers == frozenset({"lakera", "nemo"})

    def test_default_thresholds(self) -> None:
        cfg = GuardrailsConfig()
        assert cfg.thresholds == GuardrailsThresholds()

    def test_default_block_on_failure_false(self) -> None:
        cfg = GuardrailsConfig()
        assert cfg.block_on_failure is False


class TestGuardrailsConfigExplicit:
    """Явные значения."""

    def test_custom_providers_set(self) -> None:
        cfg = GuardrailsConfig(enabled_providers=frozenset({"nemo"}))
        assert cfg.enabled_providers == frozenset({"nemo"})

    def test_empty_providers(self) -> None:
        cfg = GuardrailsConfig(enabled_providers=frozenset())
        assert cfg.enabled_providers == frozenset()

    def test_custom_thresholds(self) -> None:
        thresholds = GuardrailsThresholds(lakera_threshold=0.3)
        cfg = GuardrailsConfig(thresholds=thresholds)
        assert cfg.thresholds.lakera_threshold == 0.3

    def test_block_on_failure_true(self) -> None:
        cfg = GuardrailsConfig(block_on_failure=True)
        assert cfg.block_on_failure is True


class TestGuardrailsConfigFrozen:
    """frozen=True + slots=True — полная иммутабельность."""

    def test_cannot_reassign_providers(self) -> None:
        import dataclasses

        cfg = GuardrailsConfig()
        with __import__("pytest").raises(dataclasses.FrozenInstanceError):
            cfg.enabled_providers = frozenset()  # type: ignore[misc]

    def test_cannot_reassign_thresholds(self) -> None:
        import dataclasses

        cfg = GuardrailsConfig()
        with __import__("pytest").raises(dataclasses.FrozenInstanceError):
            cfg.thresholds = GuardrailsThresholds()  # type: ignore[misc]


class TestGetDefaultConfig:
    """get_default_config() — возвращает module-level _DEFAULT."""

    def test_returns_default(self) -> None:
        result = get_default_config()
        assert result is _DEFAULT

    def test_default_has_empty_providers(self) -> None:
        # _DEFAULT — pass-through (нет активных провайдеров)
        cfg = get_default_config()
        assert cfg.enabled_providers == frozenset()

    def test_default_block_on_failure_false(self) -> None:
        cfg = get_default_config()
        assert cfg.block_on_failure is False

    def test_default_has_default_thresholds(self) -> None:
        cfg = get_default_config()
        assert cfg.thresholds == GuardrailsThresholds()


class TestSlotsTrue:
    """slots=True — присутствует в dataclass-декораторе.

    Smoke-проверка: dataclass(slots=True) конструируется без ошибок
    (механизм слотов — ответственность stdlib, не нашего кода).
    """

    def test_slots_dataclass_constructs(self) -> None:
        cfg = GuardrailsConfig()
        # Все объявленные поля доступны
        assert hasattr(cfg, "enabled_providers")
        assert hasattr(cfg, "thresholds")
        assert hasattr(cfg, "block_on_failure")


class TestAllExports:
    """Проверка __all__."""

    def test_all_contains_both_classes(self) -> None:
        assert "GuardrailsConfig" in mod.__all__
        assert "GuardrailsThresholds" in mod.__all__
        assert len(mod.__all__) == 2

    def test_classes_importable(self) -> None:
        assert callable(GuardrailsConfig)
        assert callable(GuardrailsThresholds)


class TestBackwardCompatRebuff:
    """S172 NeMo — ``rebuff`` сохранён как legacy alias."""

    def test_rebuff_in_default_thresholds(self) -> None:
        # rebuff_threshold default есть, хотя upstream archived
        assert hasattr(GuardrailsThresholds(), "rebuff_threshold")

    def test_can_set_rebuff_threshold_explicitly(self) -> None:
        t = GuardrailsThresholds(rebuff_threshold=0.42)
        assert t.rebuff_threshold == 0.42


class TestRepr:
    """frozen dataclass имеет стабильный repr."""

    def test_thresholds_repr_contains_values(self) -> None:
        t = GuardrailsThresholds(lakera_threshold=0.42)
        r = repr(t)
        assert "0.42" in r
        assert "GuardrailsThresholds" in r

    def test_config_repr_contains_class_name(self) -> None:
        cfg = GuardrailsConfig()
        r = repr(cfg)
        assert "GuardrailsConfig" in r


class TestEquality:
    """dataclass eq — структурное равенство."""

    def test_thresholds_equal_when_same_values(self) -> None:
        a = GuardrailsThresholds(lakera_threshold=0.5)
        b = GuardrailsThresholds(lakera_threshold=0.5)
        assert a == b

    def test_thresholds_not_equal_when_different(self) -> None:
        a = GuardrailsThresholds(lakera_threshold=0.5)
        b = GuardrailsThresholds(lakera_threshold=0.7)
        assert a != b

    def test_config_equal_when_same_values(self) -> None:
        a = GuardrailsConfig()
        b = GuardrailsConfig()
        assert a == b


class TestHashable:
    """frozen dataclass — hashable."""

    def test_thresholds_hashable(self) -> None:
        t = GuardrailsThresholds()
        # Должно работать в set/dict
        s = {t, t}
        assert len(s) == 1

    def test_config_hashable(self) -> None:
        cfg = GuardrailsConfig()
        s = {cfg, cfg}
        assert len(s) == 1