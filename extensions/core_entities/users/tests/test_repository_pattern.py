"""Тесты на repository pattern (CRUD) для users."""
# ruff: noqa: S101
from __future__ import annotations


def test_repository_inherits_sqlalchemy_base() -> None:
    from src.backend.core.repositories.base import SQLAlchemyRepository
    from extensions.core_entities.users.repositories.users import UserRepository
    assert issubclass(UserRepository, SQLAlchemyRepository)


def test_repository_class_instantiable() -> None:
    from extensions.core_entities.users.repositories.users import UserRepository
    from extensions.core_entities.users.domain.models import User
    repo = UserRepository(model=User)
    assert repo.model is User


def test_repository_load_joined_models_default_false() -> None:
    from extensions.core_entities.users.repositories.users import UserRepository
    from extensions.core_entities.users.domain.models import User
    repo = UserRepository(model=User)
    assert repo.load_joined_models is False


def test_repository_has_get_by_username() -> None:
    """UserRepository имеет специфичный метод get_by_username (per protocol)."""
    from extensions.core_entities.users.repositories.users import UserRepository
    from extensions.core_entities.users.domain.models import User
    repo = UserRepository(model=User)
    assert hasattr(repo, "get_by_username")


def test_repository_respects_facade_boundary() -> None:
    import extensions.core_entities.users.repositories.users as mod
    import inspect
    src = inspect.getsource(mod)
    assert "core.repositories.base" in src, (
        "UserRepository должен импортировать через core facade (D102)"
    )
    assert "infrastructure.repositories.base" not in src, (
        "UserRepository НЕ должен импортировать напрямую из infrastructure"
    )
