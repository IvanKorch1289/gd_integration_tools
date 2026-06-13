"""Re-export ORM-моделей Order для миграции (Sprint 7, R-V15-16).

Фактическое определение SQLAlchemy-модели пока остаётся в
``src.backend.core.domain.models.orders`` (миграция
БД-моделей — отдельная задача). Этот модуль предоставляет публичный
re-export, чтобы потребители плагина могли импортировать модель
через ``extensions.core_entities.orders.domain.models``.
"""

from __future__ import annotations

from src.backend.core.domain.models.orders import Order

__all__ = ("Order",)
