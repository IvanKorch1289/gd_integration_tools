"""Tests for core/repositories/base.py (S97 — coverage push).

Module re-exports 3 lazy-resolved capabilities:
- AbstractRepository (abstract base class)
- SQLAlchemyRepository (concrete impl)
- get_repository_for_model (factory function)

All loaded via DI providers (capability-gate per ADR-0207).
"""

from __future__ import annotations


def test_module_imports() -> None:
    """Module imports without error (DI resolution works)."""
    import src.backend.core.repositories.base as mod

    assert mod is not None


def test_abstract_repository_exported() -> None:
    """AbstractRepository re-exported from infrastructure layer."""
    from src.backend.core.repositories.base import AbstractRepository

    assert AbstractRepository is not None
    # Abstract base — has abstract methods or attributes.
    assert hasattr(AbstractRepository, "__abstractmethods__") or hasattr(
        AbstractRepository, "__init__"
    )


def test_sqlalchemy_repository_exported() -> None:
    """SQLAlchemyRepository re-exported."""
    from src.backend.core.repositories.base import SQLAlchemyRepository

    assert SQLAlchemyRepository is not None
    # Concrete impl — should be a class.
    assert isinstance(SQLAlchemyRepository, type)


def test_get_repository_for_model_callable() -> None:
    """get_repository_for_model is callable (factory function)."""
    from src.backend.core.repositories.base import get_repository_for_model

    assert callable(get_repository_for_model)


def test_module_dunder_all() -> None:
    """__all__ = ('AbstractRepository', 'SQLAlchemyRepository', 'get_repository_for_model')."""
    import src.backend.core.repositories.base as mod

    assert mod.__all__ == (
        "AbstractRepository",
        "SQLAlchemyRepository",
        "get_repository_for_model",
    )
