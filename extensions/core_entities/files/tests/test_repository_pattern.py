"""Тесты на repository pattern (CRUD) для files."""
# ruff: noqa: S101
from __future__ import annotations


def test_repository_inherits_sqlalchemy_base() -> None:
    from src.backend.core.repositories.base import SQLAlchemyRepository
    from extensions.core_entities.files.repositories.files import FileRepository
    assert issubclass(FileRepository, SQLAlchemyRepository)


def test_repository_class_instantiable() -> None:
    from extensions.core_entities.files.repositories.files import FileRepository
    from extensions.core_entities.files.domain.models import File, OrderFile
    repo = FileRepository(model=File, load_joined_models=False, link_model=OrderFile)
    assert repo.model is File
    assert repo.link_model is OrderFile


def test_repository_has_add_link() -> None:
    """FileRepository имеет специфичный метод add_link (per protocol)."""
    from extensions.core_entities.files.repositories.files import FileRepository
    from extensions.core_entities.files.domain.models import File, OrderFile
    repo = FileRepository(model=File, load_joined_models=False, link_model=OrderFile)
    assert hasattr(repo, "add_link")


def test_repository_respects_facade_boundary() -> None:
    import extensions.core_entities.files.repositories.files as mod
    import inspect
    src = inspect.getsource(mod)
    assert "core.repositories.base" in src, (
        "FileRepository должен импортировать через core facade (D102)"
    )
    assert "infrastructure.repositories.base" not in src, (
        "FileRepository НЕ должен импортировать напрямую из infrastructure"
    )
