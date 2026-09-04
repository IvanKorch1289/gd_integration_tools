"""Capability-checked facade для database session manager (S120 W3).

ADR-0207: extensions/* импортируют ``main_session_manager`` из
``infrastructure.database.session_manager``. Этот модуль содержит
concrete impl (SQLAlchemy async session lifecycle), которые не должны
протекать в extensions.

Этот facade переносит публичную поверхность в ``core.database``.

C1 (ledger, 2026-09-04): резолв ленивый (PEP 562 module ``__getattr__``)
— импорт модуля больше НЕ конструирует ``DatabaseSessionManager`` и не
дергает Vault по сети. Раньше ``main_session_manager = factory()`` на
уровне модуля делал сетевой вызов при каждом импорте (источник флака
коллекции тестов и задержек старта). Семантика для потребителей не
менялась: ``from ...session import main_session_manager`` работает как
раньше (резолв в момент from-import у потребителя).

Migration path:
- ``from src.backend.infrastructure.database.session_manager import main_session_manager``
  → ``from src.backend.core.database.session import main_session_manager``

Related:
- AGENTS.md (boundary rules)
- ADR-0207 (S120 W5 closure)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.core.di.providers.infrastructure_locator import (
    get_main_session_manager_factory as _get_main_session_mgr,
)
from src.backend.core.di.providers.infrastructure_locator import (
    get_main_session_manager_getter as _get_main_session_mgr_getter,
)

__all__ = ("get_main_session_manager", "main_session_manager")

if TYPE_CHECKING:  # pragma: no cover — только для статических проверок
    main_session_manager: Any
    get_main_session_manager: Any


def __getattr__(name: str) -> Any:
    """PEP 562: ленивый резолв в точке первого доступа (C1)."""
    if name == "main_session_manager":
        return _get_main_session_mgr()
    if name == "get_main_session_manager":
        return _get_main_session_mgr_getter()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
