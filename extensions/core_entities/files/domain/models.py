"""Re-export ORM-моделей File / OrderFile для миграции (Sprint 7, R-V15-16).

Фактическое определение SQLAlchemy-моделей пока остаётся в
``src.backend.infrastructure.database.models.files`` (миграция БД-моделей —
отдельная задача). Этот модуль предоставляет публичный re-export, чтобы
потребители плагина могли импортировать модели через
``extensions.core_entities.files.domain.models``.
"""

from __future__ import annotations

from src.backend.infrastructure.database.models.files import File, OrderFile

__all__ = ("File", "OrderFile")
