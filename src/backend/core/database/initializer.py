"""Capability-checked facade для database initializer (S124 W1 bonus).

ADR-0207: services/ai/langmem_service.py импортирует ``get_db_initializer``
из ``infrastructure.database.session_manager`` для доступа к
``async_session_maker`` (private attr, не module-level export).
"""

from __future__ import annotations

from src.backend.core.di.providers.infrastructure_facade import (  # noqa: F401
    get_db_initializer_factory as _get_db_initializer_fn,
)
get_db_initializer = _get_db_initializer_fn()

__all__ = ("get_db_initializer",)
