"""Capability-checked facade для database session manager (S120 W3).

ADR-0207: extensions/* импортируют ``main_session_manager`` из
``infrastructure.database.session_manager``. Этот модуль содержит
concrete impl (SQLAlchemy async session lifecycle), которые не должны
протекать в extensions.

Этот facade переносит публичную поверхность в ``core.database``.

Migration path:
- ``from src.backend.infrastructure.database.session_manager import main_session_manager``
  → ``from src.backend.core.database.session import main_session_manager``

Related:
- AGENTS.md (boundary rules)
- ADR-0207 (S120 W5 closure)
"""

from __future__ import annotations

from src.backend.infrastructure.database.session_manager import (  # noqa: F401
    get_main_session_manager,
    main_session_manager,
)

__all__ = ("get_main_session_manager", "main_session_manager")
