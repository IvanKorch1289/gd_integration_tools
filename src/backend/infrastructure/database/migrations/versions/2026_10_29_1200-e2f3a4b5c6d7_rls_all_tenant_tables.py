"""ADR-0386: RLS-политики на ВСЕХ tenant-таблицах (tenant_id).

Revision ID: e2f3a4b5c6d7
Revises: f1a2b3c4d5e6
Create Date: 2026-10-29 12:00:00.000000

Контекст
---------
До этой миграции RLS был включён только на трёх таблицах
(``workflow_instances`` — ``2026_05_22_1000``, ``workflow_state`` —
``2026_05_22_1100``, ``rule_engine_rulesets`` — там же), тогда как
колонка ``tenant_id`` к этому моменту есть у десяти таблиц: ``orders``,
``users``, ``files``, ``dsl_snapshots``, ``workflow_events``, ``orderkinds``,
``scheduler_run_history`` (миграции S89/S91/S92/S101/S171/ADR-0346).
ORM-фильтр (``core/tenancy/sqlalchemy_filter.py``) закрывал ORM- и
session-level raw-SQL пути, но не давал defense-in-depth на уровне БД.

Решение
-------
* RLS + политика ``tenant_id = current_setting('app.tenant_id', true)``
  включается для каждой таблицы из :data:`RLS_TABLES`.
* Для таблиц с nullable ``tenant_id`` (``rule_engine_rulesets``) глобальные
  строки (``tenant_id IS NULL``) остаются видимыми — как и в исходной
  политике S21. ``USING`` и ``WITH CHECK`` совпадают: глобальная строка
  (``tenant_id IS NULL``) проходит и на чтение, и на запись.
* Для уже покрытых таблиц legacy-политика (``tenant_isolation_wfi`` и др.)
  заменяется канонической ``tenant_isolation_<table>`` — иначе на таблице
  останутся две политики.
* PostgreSQL-only: на других диалектах — no-op (RLS — PG-specific feature).
* Таблица, которой в конкретной установке нет (extension-таблицы
  ``orders``/``users``/``files``/``orderkinds``), пропускается — блок
  ``DO $$ ... IF EXISTS (information_schema)`` идемпотентен.

Вне охвата (осознанно)
----------------------
* ``audit_log_immutable`` — append-only immutable audit: tenant-скоуп там
  nullable, а запись идёт из системного контура (триггер/служебный код),
  RLS на ней ломает append-поток. Решение wave 17 — не трогать.
* ``dlq_inbox`` — фоновая запись DLQ (``InboxDLQWriter``) вне
  tenant-контекста: ``WITH CHECK`` отклонил бы записи tenant-tagged
  сообщений, а чтение скрыло бы их от dispatcher'а. Follow-up: связать
  tenant-скоуп в writer'е, затем включить RLS.
* ``scheduler_run_history`` — scheduler работает вне tenant-контекста
  (``services/scheduler`` не вызывает ``bind_tenant``), ``tenant_id``
  опционален. RLS скрыл бы от scheduler'а per-tenant строки (риск
  двойного исполнения тика). Follow-up: tenant-скоуп в scheduler.
* ``langmem_episodic`` / ``langmem_procedural`` — изоляция по колонке
  ``tenant`` (не ``tenant_id``), политика ``current_setting`` к ним не
  применима.
* Внешние БД (external database profiles) — другая СУБД, свой контур.

Безопасность
------------
* Приложение обязано выставлять ``app.tenant_id`` до первой транзакции
  (делает ``core/tenancy/sqlalchemy_filter.py`` — session-event
  ``after_begin``). Без этого ``current_setting('app.tenant_id', true)``
  вернёт ``NULL``: strict-политики не пропустят ни одной строки, а
  global-политики пропустят глобальные строки.
* ``FORCE ROW LEVEL SECURITY`` — политика действует и для владельца
  таблицы (иначе owner её обходит).
"""

from __future__ import annotations

from typing import NamedTuple, Sequence, Union

from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


class RLSTable(NamedTuple):
    """Спецификация RLS-политики для одной tenant-таблицы.

    Attributes:
        name: Имя таблицы.
        allow_global: ``True`` — глобальные строки (``tenant_id IS NULL``)
            остаются видимыми; ``False`` — строгая изоляция.
        legacy_policy: Имя политики из предыдущих миграций (её нужно
            удалить при upgrade и восстановить при downgrade).

    """

    name: str
    allow_global: bool = False
    legacy_policy: str | None = None


#: Полный список tenant-таблиц (``tenant_id``) с RLS-политикой.
RLS_TABLES: tuple[RLSTable, ...] = (
    # Уже покрыты S21 (политика заменяется на каноническую).
    RLSTable("workflow_instances", legacy_policy="tenant_isolation_wfi"),
    RLSTable("workflow_state", legacy_policy="tenant_isolation_workflow_state"),
    RLSTable(
        "rule_engine_rulesets",
        allow_global=True,
        legacy_policy="tenant_isolation_rule_engine",
    ),
    # Добавлены волнами S89/S91/S92/S101/S171/ADR-0346.
    RLSTable("orders"),
    RLSTable("users"),
    RLSTable("files"),
    RLSTable("dsl_snapshots"),
    RLSTable("workflow_events"),
    RLSTable("orderkinds"),
)

#: Таблицы с ``tenant_id``, сознательно оставленные без RLS (таблица → причина).
EXCLUDED_TABLES: dict[str, str] = {
    "audit_log_immutable": (
        "append-only immutable audit: запись из системного контура, "
        "tenant-скоуп nullable — RLS ломает append-поток"
    ),
    "dlq_inbox": (
        "фоновая запись DLQ вне tenant-контекста: WITH CHECK отклонил бы "
        "tenant-tagged сообщения (follow-up: tenant-скоуп в InboxDLQWriter)"
    ),
    "scheduler_run_history": (
        "scheduler работает вне tenant-контекста, tenant_id опционален: "
        "RLS скрыл бы per-tenant строки от scheduler'а (follow-up: "
        "tenant-скоуп в scheduler)"
    ),
}

#: Выражение tenant-предиката (экранировано для ``EXECUTE``-строки).
_STRICT_PREDICATE = "tenant_id = current_setting(''app.tenant_id'', true)"
_GLOBAL_PREDICATE = f"tenant_id IS NULL OR {_STRICT_PREDICATE}"


def policy_name(table: str) -> str:
    """Каноническое имя RLS-политики для таблицы.

    Args:
        table: Имя таблицы.

    Returns:
        Имя политики вида ``tenant_isolation_<table>``.

    """
    return f"tenant_isolation_{table}"


def _predicate(allow_global: bool) -> str:
    """Выражение ``USING`` для политики (экранировано для ``EXECUTE``).

    Args:
        allow_global: Допускать ли глобальные строки (``tenant_id IS NULL``).

    Returns:
        SQL-выражение tenant-предиката.

    """
    return _GLOBAL_PREDICATE if allow_global else _STRICT_PREDICATE


def _table_exists_clause(table: str) -> str:
    """Условие существования таблицы в текущей схеме.

    Args:
        table: Имя таблицы.

    Returns:
        SQL-условие для ``IF EXISTS``.

    """
    return (
        "IF EXISTS (\n"  # noqa: S608  # nosec B608 — table: литерал из RLS_TABLES
        "            SELECT 1 FROM information_schema.tables\n"
        "            WHERE table_schema = current_schema()\n"
        f"              AND table_name = '{table}'\n"
        "        ) THEN"
    )


def _enable_block(table: RLSTable) -> str:
    """Сгенерировать idempotent-блок включения RLS для таблицы.

    Args:
        table: Спецификация таблицы.

    Returns:
        SQL-блок (``DO $$ ... $$;``) для ``op.execute``.

    """
    name = table.name
    policy = policy_name(name)
    legacy_drop = (
        f"        EXECUTE 'DROP POLICY IF EXISTS {table.legacy_policy} ON {name}';\n"
        if table.legacy_policy
        else ""
    )
    return f"""
DO $$
BEGIN
    {_table_exists_clause(name)}
        EXECUTE 'ALTER TABLE {name} ENABLE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE {name} FORCE ROW LEVEL SECURITY';
        EXECUTE 'DROP POLICY IF EXISTS {policy} ON {name}';
{legacy_drop}        EXECUTE 'CREATE POLICY {policy} ON {name} '
            || 'USING ({_predicate(table.allow_global)}) '
            || 'WITH CHECK ({_predicate(table.allow_global)})';
    END IF;
END
$$;
"""


def _disable_block(table: RLSTable) -> str:
    """Сгенерировать блок отката RLS для таблицы.

    Для таблиц, покрытых предыдущими миграциями, RLS остаётся включённым,
    а legacy-политика восстанавливается; для новых таблиц RLS выключается.

    Args:
        table: Спецификация таблицы.

    Returns:
        SQL-блок (``DO $$ ... $$;``) для ``op.execute``.

    """
    name = table.name
    policy = policy_name(name)
    if table.legacy_policy is None:
        return f"""
DO $$
BEGIN
    {_table_exists_clause(name)}
        EXECUTE 'DROP POLICY IF EXISTS {policy} ON {name}';
        EXECUTE 'ALTER TABLE {name} DISABLE ROW LEVEL SECURITY';
    END IF;
END
$$;
"""
    legacy = table.legacy_policy
    return f"""
DO $$
BEGIN
    {_table_exists_clause(name)}
        EXECUTE 'DROP POLICY IF EXISTS {policy} ON {name}';
        EXECUTE 'DROP POLICY IF EXISTS {legacy} ON {name}';
        EXECUTE 'CREATE POLICY {legacy} ON {name} '
            || 'USING ({_predicate(table.allow_global)})';
    END IF;
END
$$;
"""


def upgrade() -> None:
    """Включить RLS + tenant-политику на всех tenant-таблицах.

    PostgreSQL-only: на других диалектах — no-op с комментарием
    (RLS — PostgreSQL-specific feature).
    """
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table in RLS_TABLES:
        op.execute(_enable_block(table))


def downgrade() -> None:
    """Откатить RLS-политики, добавленные этой миграцией.

    Для таблиц, покрытых предыдущими миграциями, восстанавливается
    legacy-политика (RLS остаётся включённым); для новых таблиц RLS
    выключается.
    """
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table in RLS_TABLES:
        op.execute(_disable_block(table))
