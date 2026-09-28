"""Канонический primitive для PII-erasure в реляционной БД (ADR-0347).

PII хранится в динамических таблицах ``{entity_type}_pii`` с колонкой
``entity_id`` (и опционально ``tenant_id``). Именно эту схему использует
production-путь ``dsl/engine/processors/security/pii_erase.py``.

Раньше существовали ДВЕ разные реализации этого механизма:

* ``pii_erase`` (DSL) — рабочая, с whitelist идентификатора;
* ``PostgresErasureAdapter`` (core/privacy) — ссылалась на несуществующий
  ``core.domain.models.privacy_models.PiiErasureRecord`` и падала
  ``ModuleNotFoundError`` на каждом вызове.

Причина: приватные helpers были внутри DSL-модуля, и ``core`` не может их
импортировать (core не зависит от dsl). Канонический primitive обязан жить
в ``core`` — тогда и адаптер, и DSL-процессор используют одну реализацию
(«One canonical implementation per capability») без нарушения слоёв.
"""

from __future__ import annotations

import re

__all__ = (
    "ENTITY_TYPE_RE",
    "build_anonymize_sql",
    "build_delete_sql",
    "pii_table_for_subject",
    "pii_table_name",
    "validate_entity_type",
)

# Whitelist для entity_type: только [A-Za-z_][A-Za-z0-9_]* — совпадает с
# ``db_crud._IDENTIFIER_RE`` и с исходным ``pii_erase._ENTITY_TYPE_RE``.
ENTITY_TYPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_entity_type(entity_type: str) -> str:
    """Проверить ``entity_type`` по whitelist и вернуть его же.

    S608 mitigation: ``entity_type`` подставляется в SQL только как
    safe-identifier, значения всегда биндятся параметрами.

    Args:
        entity_type: Тип сущности.

    Returns:
        Валидированный ``entity_type``.

    Raises:
        ValueError: Если значение не проходит whitelist.

    """
    if not ENTITY_TYPE_RE.fullmatch(entity_type):
        raise ValueError(
            f"invalid entity_type {entity_type!r} (only [A-Za-z_][A-Za-z0-9_]* allowed)"
        )
    return entity_type


def pii_table_name(entity_type: str) -> str:
    """Вернуть имя PII-таблицы для типа сущности.

    Args:
        entity_type: Валидируемый тип сущности (например ``"user"``).

    Returns:
        ``"{entity_type}_pii"``.

    """
    return f"{validate_entity_type(entity_type)}_pii"


def pii_table_for_subject(subject_id: str) -> str:
    """Разобрать ``subject_id`` вида ``"<entity_type>:<id>"`` в имя таблицы.

    Args:
        subject_id: Идентификатор субъекта с типом, например ``"user:42"``.

    Returns:
        ``"{entity_type}_pii"``.

    Raises:
        ValueError: Если формат неверный или тип не проходит whitelist.

    """
    if ":" not in subject_id:
        raise ValueError(
            f"subject_id должен быть '<entity_type>:<id>' "
            f"(неверный entity_type в subject_id {subject_id!r})"
        )
    entity_type, _ = subject_id.split(":", 1)
    return pii_table_name(entity_type)


def _where_clause(tenant_scoped: bool) -> str:
    """Собрать WHERE-фрагмент (безопасно: только литералы)."""
    if tenant_scoped:
        return "entity_id = :entity_id AND tenant_id = :tenant_id"
    return "entity_id = :entity_id"


def build_delete_sql(table: str, *, tenant_scoped: bool = False) -> str:
    """Собрать ``DELETE FROM {table} WHERE ...``.

    Args:
        table: Имя таблицы, полученное из :func:`pii_table_name`
            (уже провалидировано).
        tenant_scoped: Добавить ли ``tenant_id`` в условие.

    Returns:
        SQL-строка. Идентификатор таблицы безопасен (whitelist), значения
        биндятся отдельно.

    """
    return f"DELETE FROM {table} WHERE {_where_clause(tenant_scoped)}"  # noqa: S608 — table from pii_table_name() (whitelist)


def build_anonymize_sql(table: str, *, tenant_scoped: bool = False) -> str:
    """Собрать ``UPDATE {table} SET <pii cols> = NULL ...``.

    Args:
        table: Валидированное имя таблицы.
        tenant_scoped: Добавить ли ``tenant_id`` в условие.

    Returns:
        SQL-строка.

    """
    return (
        f"UPDATE {table} SET name = NULL, email = NULL, phone = NULL, "  # noqa: S608 — table from pii_table_name() (whitelist)
        # CURRENT_TIMESTAMP (не NOW()) — работает и в PostgreSQL, и в SQLite,
        # поэтому primitive исполняем в dev/test-окружении (ADR-0347).
        f"anonymized_at = CURRENT_TIMESTAMP WHERE {_where_clause(tenant_scoped)}"
    )
