"""Тесты на repository pattern (CRUD) для orderkinds."""
# ruff: noqa: S101
from __future__ import annotations


def test_repository_inherits_sqlalchemy_base() -> None:
    """Test: repository inherits sqlalchemy base."""
    from extensions.core_entities.orderkinds.repositories.orderkinds import (
        OrderKindRepository,
    )
    from src.backend.core.api import SQLAlchemyRepository
    assert issubclass(OrderKindRepository, SQLAlchemyRepository)


def test_repository_class_instantiable() -> None:
    """Test: repository class instantiable."""
    from extensions.core_entities.orderkinds.domain.models import OrderKind
    from extensions.core_entities.orderkinds.repositories.orderkinds import (
        OrderKindRepository,
    )
    repo = OrderKindRepository(model=OrderKind)
    assert repo.model is OrderKind


def test_repository_respects_facade_boundary() -> None:
    """Test: repository respects facade boundary."""
    import inspect

    import extensions.core_entities.orderkinds.repositories.orderkinds as mod
    src = inspect.getsource(mod)
    assert "core.repositories.base" in src, (
        "OrderKindRepository должен импортировать через core facade (D102)"
    )
    assert "infrastructure.repositories.base" not in src, (
        "OrderKindRepository НЕ должен импортировать напрямую из infrastructure"
    )
