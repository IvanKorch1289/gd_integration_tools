"""Extension package: core_entities.

2026-10-06 (R-V15-16): импорт всех доменных расширений нужен, чтобы
SQLAlchemy ORM-таблицы оказались на общем ``Base.metadata`` до любых
операций (autogenerate миграций, ``metadata.create_all``). У каждого
расширения свой FK в ``orders``: ``Order.order_kind_id → orderkinds.id``
и ``OrderFile → files`` — без двух соседних таблиц создание схемы
падает с ``NoReferencedTableError``.

Подмодули импортируются явно (не через ``*``), чтобы сборка импорта
была видна при диагностике.
"""

from __future__ import annotations

from . import files, orderkinds, orders, users  # noqa: F401 — side-effect

__all__ = ("files", "orderkinds", "orders", "users")
