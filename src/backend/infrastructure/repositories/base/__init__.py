"""Repository base classes (S64 W2 decomp from base.py 491 LOC).

2 classes + 1 helper → 3 files (per-pattern, S55 W1 cert_store style):
- ``base.py``: AbstractRepository (9 methods ABC)
- ``sqlalchemy.py``: SQLAlchemyRepository (11 methods concrete impl)
- ``factory.py``: get_repository_for_model

Backward-compat: ``from src.backend.infrastructure.repositories.base import AbstractRepository`` works.
"""

from __future__ import annotations

from src.backend.infrastructure.repositories.base.base import (
    AbstractRepository,  # S64 W2: re-export
)
from src.backend.infrastructure.repositories.base.factory import (
    get_repository_for_model,  # S64 W2: re-export
)
from src.backend.infrastructure.repositories.base.sqlalchemy import (
    SQLAlchemyRepository,  # S64 W2: re-export
)

__all__ = ("AbstractRepository", "SQLAlchemyRepository", "get_repository_for_model")
