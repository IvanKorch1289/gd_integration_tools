"""Capability-checked facade для repository base classes (S120 W1).

ADR-0207: extensions/* импортируют ТОЛЬКО ``core.*`` + capability-checked
фасады. ``infrastructure.repositories.base`` содержит concrete impl
(SQLAlchemy), которые не должны протекать в extensions.

Этот модуль — thin re-export + deprecation note. Прямой импорт
``infrastructure.repositories.base.*`` из extensions — architectural
violation, заменяется на этот facade.

Migration path:
- ``from src.backend.infrastructure.repositories.base import SQLAlchemyRepository``
  → ``from src.backend.core.repositories.base import SQLAlchemyRepository``

Related:
- AGENTS.md (boundary rules)
- ADR-0207 (S120 W5 closure)
"""

from __future__ import annotations

# Re-exports (capability-checked: extensions имеют право на эти классы,
# но не на private helpers из infrastructure.repositories.base.*).
from src.backend.core.di.providers.infrastructure_facade import (  # noqa: F401
    get_abstract_repository_class as _get_ar_cls,
    get_sqlalchemy_repository_class as _get_sr_cls,
    get_repository_for_model_factory as _get_rfm_fn,
)
AbstractRepository = _get_ar_cls()
SQLAlchemyRepository = _get_sr_cls()
get_repository_for_model = _get_rfm_fn()

__all__ = ("AbstractRepository", "SQLAlchemyRepository", "get_repository_for_model")
