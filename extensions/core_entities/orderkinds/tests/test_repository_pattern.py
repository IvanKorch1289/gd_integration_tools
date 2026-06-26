"""Тесты на repository pattern (CRUD) для orderkinds."""
# ruff: noqa: S101
from __future__ import annotations


def test_repository_inherits_sqlalchemy_base() -> None:
    from src.backend.core.repositories.base import SQLAlchemyRepository
    from extensions.core_entities.orderkinds.repositories.orderkinds import OrderKindRepository
    assert issubclass(OrderKindRepository, SQLAlchemyRepository)


def test_repository_class_instantiable() -> None:
    from extensions.core_entities.orderkinds.repositories.orderkinds import OrderKindRepository
    from extensions.core_entities.orderkinds.domain.models import OrderKind
    repo = OrderKindRepository(model=OrderKind)
    assert repo.model is OrderKind


def test_repository_respects_facade_boundary() -> None:
    import extensions.core_entities.orderkinds.repositories.orderkinds as mod
    import inspect
    src = inspect.getsource(mod)
    assert "core.repositories.base" in src, (
        "OrderKindRepository должен импортировать через core facade (D102)"
    )
    assert "infrastructure.repositories.base" not in src, (
        "OrderKindRepository НЕ должен импортировать напрямую из infrastructure"
    )
