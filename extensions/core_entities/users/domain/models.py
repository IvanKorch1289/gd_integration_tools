"""Re-export ORM-моделей User для миграции (Sprint 7, R-V15-16).

S106 W1 (D5 B1) перенёс SQLAlchemy-модели в ``core/domain/models/``.
Импорт через ``core.domain.models.users`` — canonical. Этот модуль —
re-export для удобства extensions-импорта.
"""
from __future__ import annotations

from src.backend.core.domain.models.users import User

__all__ = ("User",)
