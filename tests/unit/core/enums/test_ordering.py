"""Tests for core/enums/ordering.py (cycle 229 — coverage push).

Per CYCLE-220 analysis, coverage target 77% → 80% (analyst #12).
`core/enums/ordering.py` (17 LOC) — small public Enum без тестов.
"""

from __future__ import annotations

import pytest

from src.backend.core.enums.ordering import OrderingTypeChoices


def test_ordering_has_two_values() -> None:
    """Enum имеет 2 значения: ascending, descending."""
    assert len(OrderingTypeChoices) == 2


def test_ordering_ascending_value() -> None:
    """`ascending = 'asc'` — string value, lowercase."""
    assert OrderingTypeChoices.ascending.value == "asc"


def test_ordering_descending_value() -> None:
    """`descending = 'desc'` — string value, lowercase."""
    assert OrderingTypeChoices.descending.value == "desc"


def test_ordering_by_value() -> None:
    """Получить enum по значению."""
    assert OrderingTypeChoices("asc") is OrderingTypeChoices.ascending
    assert OrderingTypeChoices("desc") is OrderingTypeChoices.descending


def test_ordering_invalid_value() -> None:
    """Invalid value raises ValueError."""
    with pytest.raises(ValueError):
        OrderingTypeChoices("not_a_value")


def test_ordering_dunder_all() -> None:
    """`__all__` = ('OrderingTypeChoices',)."""
    import src.backend.core.enums.ordering as mod
    assert mod.__all__ == ("OrderingTypeChoices",)


def test_ordering_distinct_values() -> None:
    """Каждое значение уникально."""
    values = [m.value for m in OrderingTypeChoices]
    assert len(values) == len(set(values))
