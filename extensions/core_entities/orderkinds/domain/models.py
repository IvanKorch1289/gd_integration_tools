"""Re-export ORM-моделей OrderKind для миграции (Sprint 7, R-V15-16).

Фактическое определение SQLAlchemy-модели пока остаётся в
``src.backend.infrastructure.database.models.orderkinds`` (миграция
БД-моделей — отдельная задача). Этот модуль предоставляет публичный
re-export, чтобы потребители плагина могли импортировать модель
через ``extensions.core_entities.orderkinds.domain.models``.
"""

from __future__ import annotations

from src.backend.infrastructure.database.models.orderkinds import OrderKind

__all__ = ("OrderKind",)
