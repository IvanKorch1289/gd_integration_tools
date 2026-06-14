"""Capability-checked facade для BaseService (S120 W3).

ADR-0207: extensions/* services импортируют ``BaseService`` из
``services.core.base``. Это базовый класс для CRUD-сервисов с
mixin'ами (cache/crud/versioning). Не должен протекать в extensions —
должен быть в ``core.services.base_service``.

Migration path:
- ``from src.backend.services.core.base import BaseService``
  → ``from src.backend.core.services.base_service import BaseService``

Related:
- AGENTS.md (boundary rules)
- ADR-0207 (S120 W5 closure)
"""

from __future__ import annotations

from src.backend.services.core.base import (  # noqa: F401
    BaseService,
    create_service_class,
    get_service_for_model,
)

__all__ = (
    "BaseService",
    "create_service_class",
    "get_service_for_model",
)
