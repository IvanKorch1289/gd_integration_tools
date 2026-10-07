"""Extension package: domain.

SQLAlchemy ORM-модели объявляются на общем ``BaseModel`` из
``src.backend.core.domain.models.base``. Side-effect импорта
``extensions.core_entities.files.domain.models`` нужен, чтобы таблицы
регистрировались в ``Base.metadata`` и попадали в Alembic autogenerate
через :func:`load_plugin_manifests_for_migrations` (cycle-15).

Раньше регистрация шла через реэкспорт в
``src.backend.core.domain.models.__init__`` — это создавало прямую
зависимость ``core → extensions`` и попало в allowlist гейта слоёв.
Инверсия (R-V15-16): каждый extension отвечает за свои таблицы сам.
"""

from __future__ import annotations

from . import models  # noqa: F401 — side-effect: register tables on Base.metadata

__all__ = ("models",)
