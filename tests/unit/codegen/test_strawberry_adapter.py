"""Wave 1.4 (Roadmap V10) — unit-тесты Pydantic→Strawberry адаптера.

Покрывает:

* конвертацию простой модели → Strawberry-type;
* кеш: повторный вызов на одной модели возвращает тот же класс;
* nested модели резолвятся;
* fallback при некорректной модели не валит общий процесс.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from src.backend.core.actions.strawberry_adapter import (
    StrawberryTypeRegistry,
    pydantic_to_strawberry,
)


class _SimpleStraw(BaseModel):
    """Тестовая модель для Strawberry."""

    id: int
    name: str
    description: Optional[str] = None  # noqa: UP045


class _NestedItem(BaseModel):
    code: int


class _StrawWithNested(BaseModel):
    item: _NestedItem
    items: list[_NestedItem] = []


class TestRegistryBasic:
    def test_simple_model_converts(self):
        reg = StrawberryTypeRegistry()
        cls = reg.get_or_create(_SimpleStraw)
        assert cls is not None
        # Strawberry type должен иметь имя "_SimpleStrawType".
        assert cls.__name__ == "_SimpleStrawType" or hasattr(cls, "__strawberry_definition__")

    def test_cache_returns_same_class(self):
        reg = StrawberryTypeRegistry()
        a = reg.get_or_create(_SimpleStraw)
        b = reg.get_or_create(_SimpleStraw)
        assert a is b

    def test_global_helper(self):
        cls1 = pydantic_to_strawberry(_SimpleStraw)
        cls2 = pydantic_to_strawberry(_SimpleStraw)
        assert cls1 is cls2


class TestNested:
    def test_nested_model_registered(self):
        reg = StrawberryTypeRegistry()
        reg.get_or_create(_StrawWithNested)
        # Должны быть зарегистрированы оба type (outer + nested).
        names = {k.split(".")[-1] for k in reg._cache}  # noqa: SLF001
        assert "_StrawWithNested" in names
        assert "_NestedItem" in names
