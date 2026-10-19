"""Tests for ``src.backend.core.types.side_effect``.

W14.4: ``SideEffectKind`` StrEnum — классификация side-effects
процессоров и actions:
- PURE: детерминированная функция, безопасен retry
- STATEFUL: мутирует внутреннее состояние, retry в одном процессе
- SIDE_EFFECTING: внешний эффект, требует idempotency_key

Используется engine для retry-стратегии, SagaProcessor для
compensation, Streamlit Console для отображения effect_class.
"""

from __future__ import annotations

import json
from enum import StrEnum

import pytest

from src.backend.core.types.side_effect import SideEffectKind


class TestSideEffectKindMembers:
    """Проверка enum members."""

    def test_pure_exists(self) -> None:
        assert hasattr(SideEffectKind, "PURE")

    def test_stateful_exists(self) -> None:
        assert hasattr(SideEffectKind, "STATEFUL")

    def test_side_effecting_exists(self) -> None:
        assert hasattr(SideEffectKind, "SIDE_EFFECTING")

    def test_total_three_members(self) -> None:
        """Только 3 значения: PURE, STATEFUL, SIDE_EFFECTING."""
        assert len(SideEffectKind) == 3

    def test_all_members_listed(self) -> None:
        assert set(SideEffectKind.__members__) == {
            "PURE",
            "STATEFUL",
            "SIDE_EFFECTING",
        }


class TestSideEffectKindValues:
    """String values для YAML/JSON сериализации."""

    def test_pure_value(self) -> None:
        assert SideEffectKind.PURE.value == "pure"

    def test_stateful_value(self) -> None:
        assert SideEffectKind.STATEFUL.value == "stateful"

    def test_side_effecting_value(self) -> None:
        assert SideEffectKind.SIDE_EFFECTING.value == "side_effecting"

    def test_unique_values(self) -> None:
        values = [d.value for d in SideEffectKind]
        assert len(values) == len(set(values))


class TestSideEffectKindStrEnumBehavior:
    """``SideEffectKind`` наследуется от ``str`` через StrEnum."""

    def test_is_strenum_subclass(self) -> None:
        assert issubclass(SideEffectKind, StrEnum)

    def test_is_str_subclass(self) -> None:
        assert isinstance(SideEffectKind.PURE, str)

    def test_str_equality(self) -> None:
        assert SideEffectKind.PURE == "pure"
        assert SideEffectKind.STATEFUL == "stateful"
        assert SideEffectKind.SIDE_EFFECTING == "side_effecting"

    def test_str_concatenation(self) -> None:
        """``SideEffectKind.PURE + "_x"`` — str concat работает."""
        assert SideEffectKind.PURE + "_x" == "pure_x"


class TestSideEffectKindSerialization:
    """YAML/JSON-friendly сериализация."""

    def test_json_serialize(self) -> None:
        data = json.dumps({"effect": SideEffectKind.PURE})
        assert data == '{"effect": "pure"}'

    def test_json_round_trip(self) -> None:
        original = {"effect": "side_effecting"}
        parsed = json.loads(json.dumps(original))
        assert SideEffectKind(parsed["effect"]) == SideEffectKind.SIDE_EFFECTING


class TestSideEffectKindLookup:
    """Lookup by value."""

    def test_lookup_pure(self) -> None:
        assert SideEffectKind("pure") == SideEffectKind.PURE

    def test_lookup_stateful(self) -> None:
        assert SideEffectKind("stateful") == SideEffectKind.STATEFUL

    def test_lookup_side_effecting(self) -> None:
        assert SideEffectKind("side_effecting") == SideEffectKind.SIDE_EFFECTING

    def test_lookup_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            SideEffectKind("unknown-effect")

    def test_lookup_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            SideEffectKind("")


class TestSideEffectKindEquality:
    """Equality и hashing."""

    def test_same_member_equal(self) -> None:
        assert SideEffectKind.PURE == SideEffectKind.PURE

    def test_different_members_not_equal(self) -> None:
        assert SideEffectKind.PURE != SideEffectKind.STATEFUL
        assert SideEffectKind.STATEFUL != SideEffectKind.SIDE_EFFECTING
        assert SideEffectKind.PURE != SideEffectKind.SIDE_EFFECTING

    def test_hashable(self) -> None:
        d = {
            SideEffectKind.PURE: "p",
            SideEffectKind.STATEFUL: "s",
            SideEffectKind.SIDE_EFFECTING: "se",
        }
        assert d[SideEffectKind.PURE] == "p"
        assert d[SideEffectKind.SIDE_EFFECTING] == "se"

    def test_in_set(self) -> None:
        s = {SideEffectKind.PURE, SideEffectKind.STATEFUL}
        assert SideEffectKind.PURE in s
        assert SideEffectKind.SIDE_EFFECTING not in s


class TestSideEffectKindExports:
    """``__all__`` exports."""

    def test_exports(self) -> None:
        from src.backend.core.types import side_effect

        assert side_effect.__all__ == ("SideEffectKind",)


class TestSideEffectKindDocumentation:
    """Документированные инварианты (для unit-теста контракта)."""

    def test_pure_safe_retry(self) -> None:
        """PURE — safe retry, кэширование, мемоизация."""
        # Это контракт; runtime-семантика проверяется в engine.
        # Тест фиксирует, что PURE существует и имеет ожидаемое значение.
        assert SideEffectKind.PURE.value == "pure"

    def test_side_effecting_requires_idempotency(self) -> None:
        """SIDE_EFFECTING — без ``idempotency_key`` риск дубликатов.

        Это контракт для SagaProcessor / retry-стратегии.
        """
        assert SideEffectKind.SIDE_EFFECTING.value == "side_effecting"
