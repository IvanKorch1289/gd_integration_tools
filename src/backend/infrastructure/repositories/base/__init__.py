"""Repository base classes (S64 W2 decomp from base.py 491 LOC).

Backward-compat: ``from src.backend.infrastructure.repositories.base import AbstractRepository`` works.
Sprint 36 — ponytail (D111): PEP 562 ``__getattr__`` для разрыва import cycle
``infrastructure.repositories.base.sqlalchemy`` ↔ ``infrastructure.database.session_manager``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.infrastructure.repositories.base.base import (
        AbstractRepository as AbstractRepository,
    )
    from src.backend.infrastructure.repositories.base.factory import (
        get_repository_for_model as get_repository_for_model,
    )
    from src.backend.infrastructure.repositories.base.sqlalchemy import (
        SQLAlchemyRepository as SQLAlchemyRepository,
    )

__all__ = ("AbstractRepository", "SQLAlchemyRepository", "get_repository_for_model")


def __getattr__(name: str) -> Any:
    if name == "AbstractRepository":
        from src.backend.infrastructure.repositories.base.base import AbstractRepository
        return AbstractRepository
    if name == "SQLAlchemyRepository":
        from src.backend.infrastructure.repositories.base.sqlalchemy import (
            SQLAlchemyRepository,
        )
        return SQLAlchemyRepository
    if name == "get_repository_for_model":
        from src.backend.infrastructure.repositories.base.factory import (
            get_repository_for_model,
        )
        return get_repository_for_model
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
