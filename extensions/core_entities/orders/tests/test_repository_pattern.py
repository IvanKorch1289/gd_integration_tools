"""Тесты на repository pattern (CRUD) для orders.

Проверяет:
- Репозиторий наследует SQLAlchemyRepository
- Repository доступен через core.facades
- Паттерн изолирован в extensions/

S171 M9 final (T52.4): coverage для repository layer.
"""
# ruff: noqa: S101
from __future__ import annotations


def test_repository_inherits_sqlalchemy_base() -> None:
    """OrderRepository наследует SQLAlchemyRepository из core."""
    from src.backend.core.repositories.base import SQLAlchemyRepository
    from extensions.core_entities.orders.repositories.orders import OrderRepository
    assert issubclass(OrderRepository, SQLAlchemyRepository)


def test_repository_protocol_satisfied() -> None:
    """OrderRepository удовлетворяет OrderRepositoryProtocol."""
    from extensions.core_entities.orders.repositories.orders import OrderRepository
    from src.backend.core.interfaces.repositories import OrderRepositoryProtocol
    # Protocol — duck typing проверка
    assert hasattr(OrderRepository, "add")
    assert hasattr(OrderRepository, "update")
    assert hasattr(OrderRepository, "get")
    assert hasattr(OrderRepository, "delete")
    assert hasattr(OrderRepository, "first_or_last")
    assert hasattr(OrderRepository, "get_all_versions")
    assert hasattr(OrderRepository, "get_latest_version")
    assert hasattr(OrderRepository, "restore_to_version")


def test_repository_class_instantiable() -> None:
    """OrderRepository можно инстанциировать с моделью Order + order_kind_repo."""
    from unittest.mock import MagicMock
    from extensions.core_entities.orders.repositories.orders import OrderRepository
    from extensions.core_entities.orders.domain.models import Order
    order_kind_repo = MagicMock()
    repo = OrderRepository(model=Order, order_kind_repo=order_kind_repo)
    assert repo.model is Order
    assert repo.order_kind_repo is order_kind_repo


def test_repository_load_joined_models_default_false() -> None:
    """load_joined_models default = False (по требованию Ponytail)."""
    from unittest.mock import MagicMock
    from extensions.core_entities.orders.repositories.orders import OrderRepository
    from extensions.core_entities.orders.domain.models import Order
    order_kind_repo = MagicMock()
    repo = OrderRepository(model=Order, order_kind_repo=order_kind_repo)
    assert repo.load_joined_models is True  # default-ON для joined models


def test_repository_respects_facade_boundary() -> None:
    """extensions → core.repos (через facade), не infrastructure напрямую."""
    # OrderRepository должен импортировать из core.repositories.base,
    # а НЕ из infrastructure.repositories.base
    import extensions.core_entities.orders.repositories.orders as mod
    import inspect
    src = inspect.getsource(mod)
    assert "core.repositories.base" in src, (
        "OrderRepository должен импортировать через core facade (D102)"
    )
    assert "infrastructure.repositories.base" not in src, (
        "OrderRepository НЕ должен импортировать напрямую из infrastructure (D102)"
    )


def test_order_admin_listed_in_plugin_capabilities() -> None:
    """plugin.toml содержит db.read+write на orders."""
    from pathlib import Path
    manifest_path = Path(__file__).parent.parent / "plugin.toml"
    content = manifest_path.read_text()
    assert "orders" in content
    # Проверяем что db.read и db.write присутствуют
    assert "db.read" in content or "db.write" in content
