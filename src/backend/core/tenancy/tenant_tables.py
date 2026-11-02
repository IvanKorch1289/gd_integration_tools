"""Канонический список tenant-таблиц (ADR-0417).

Единственный источник имён таблиц, которые обязаны быть tenant-изолированы
на уровне приложения (ORM-фильтр + raw-SQL guard) и на уровне БД (RLS).

Источник имён — миграции БД: таблицы с колонкой ``tenant_id``. Список
выводится из AST миграций в тесте
``tests/unit/infrastructure/database/test_rls_all_tenant_tables.py``
(``_tables_with_tenant_id``) и сверяется с этим модулем — расхождение
ломает тест.

Почему список явный, а не только по ORM-моделям: extension-таблицы
``orders`` / ``users`` / ``files`` / ``orderkinds`` описываются моделями в
``extensions/core_entities/*`` и загружаются **лениво** (plugin-loader), поэтому
динамическое обнаружение (``Table.after_parent_attach`` + metadata) их не
видит. На внешней БД без RLS это означало кросс-tenant чтение через raw SQL.

Состав списка совпадает с набором RLS-таблиц миграции
``2026_10_29_1200-e2f3a4b5c6d7_rls_all_tenant_tables`` — миграция импортирует
имена отсюда, чтобы scope guard'а и scope RLS не расходились.
"""

from __future__ import annotations

from typing import Final

__all__ = ("TENANT_TABLES",)


#: Таблицы с колонкой ``tenant_id``, защищаемые tenant-guard'ом.
TENANT_TABLES: Final[frozenset[str]] = frozenset(
    {
        # Ядро (ORM-модели есть — но список канонический, чтобы scope
        # не зависел от порядка импорта моделей).
        "dsl_snapshots",
        "rule_engine_rulesets",
        "workflow_events",
        "workflow_instances",
        "workflow_state",
        # Extension-таблицы (ORM-моделей в ядре нет — только в extensions/).
        "files",
        "orderkinds",
        "orders",
        "users",
    }
)
