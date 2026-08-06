#!/usr/bin/env python3
"""D-AUDIT-#15 migration script (S183 W2 #3, 2026-08-05).

# B-19 fix (cycle 38): DLQ partition migration + dry-run tests (D-AUDIT-#15).
# Read-mostly migration: dry-run by default, --confirm env-gated,
# DROP TABLE оставлен на ручное выполнение (rollback window).

ClickHouse ``dlq_events`` → ``PARTITION BY toYYYYMM(created_at)``.

Текущий cleanup-job использует ``DELETE FROM dlq_events WHERE ...``,
что в ClickHouse — мутация (ALTER ... DELETE), сканирующая всю
таблицу без partition pruning. После миграции retention-cleanup
может использовать мгновенный ``ALTER TABLE ... DROP PARTITION``.

Этот скрипт выполняет **только schema-migration** (DDL + copy data
+ atomic rename) — **runtime-cleanup изменения НЕ входят в scope**
(см. ``docs/migrations/dlq_partition_migration.md``).

Паттерн (sprint precedent): ``tools/migrations/migrate_api_keys_to_argon2.py``.

Strategy (см. docs):
1. CREATE TABLE ``dlq_events_new`` с ``PARTITION BY toYYYYMM(created_at)``.
2. ``INSERT INTO dlq_events_new SELECT * FROM dlq_events`` — copy.
3. ``RENAME TABLE dlq_events TO dlq_events_old, dlq_events_new TO dlq_events``.
4. ``DROP TABLE dlq_events_old`` — **оставлено на ручное выполнение**
   (после retention-window, чтобы был rollback).

Usage::

    # Dry-run (default) — печатает план, никаких DDL.
    python tools/migrations/migrate_dlq_partition.py \\
        --ch-url https://clickhouse.example.com \\
        --database analytics

    # Реальная миграция (требует --confirm ИЛИ env CONFIRM=1).
    CONFIRM=1 python tools/migrations/migrate_dlq_partition.py \\
        --ch-url https://clickhouse.example.com \\
        --database analytics \\
        --confirm

Safety:
* ``--dry-run`` (default) — read-only, ``client.command`` НЕ вызывается.
* ``--confirm`` обязателен для write-mode (env ``CONFIRM=1`` тоже работает).
* DROP TABLE **не выполняется** автоматически — только rename (atomic).
* Все DDL логируются перед выполнением (audit-trail в ``migration.log``).

Exit codes:
* 0 — success (dry-run или real migration).
* 1 — runtime error (CH connection / DDL failed).
* 2 — invalid args.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("tools.migrate_dlq_partition")

__all__ = (
    "MigrationPlan",
    "build_ddl_statements",
    "parse_args",
    "main",
    "run_migration",
)


@dataclass(slots=True)
class MigrationPlan:
    """План DDL-команд для миграции."""

    table_source: str = "dlq_events"
    table_new: str = "dlq_events_new"
    table_old: str = "dlq_events_old"
    database: str = "default"
    cluster: str | None = None  # None → single-node
    create_new_sql: str = ""
    copy_sql: str = ""
    rename_sql: str = ""
    statements: list[str] = field(default_factory=list)


def _qualify(name: str, database: str) -> str:
    """``dlq_events`` → ``analytics.dlq_events`` для unqualified tables."""

    return f"{database}.{name}" if "." not in name else name


def build_ddl_statements(
    *,
    table_source: str,
    table_new: str,
    database: str,
    cluster: str | None = None,
    partition_key: str = "toYYYYMM(created_at)",
) -> MigrationPlan:
    """Собрать DDL-план без выполнения.

    Возвращает :class:`MigrationPlan` с готовыми SQL-строками.
    DDL для ``CREATE TABLE ... NEW`` намеренно использует
    **обобщённую форму** — оператор должен быть скорректирован под
    реальную схему (``SHOW CREATE TABLE dlq_events``).

    Args:
        table_source: имя существующей таблицы (default ``dlq_events``).
        table_new: имя новой таблицы для copy (default ``dlq_events_new``).
        database: имя database.
        cluster: cluster-имя для ``ON CLUSTER`` (None → single-node).
        partition_key: выражение PARTITION BY.

    Returns:
        Заполненный :class:`MigrationPlan`.
    """
    src = _qualify(table_source, database)
    new = _qualify(table_new, database)
    old = _qualify(f"{table_source}_old", database)
    on_cluster = f" ON CLUSTER '{cluster}'" if cluster else ""

    # NB: точная схема должна быть взята из SHOW CREATE TABLE <src>.
    # Здесь — типовая форма с минимальным набором колонок.
    create_new_sql = (
        f"CREATE TABLE IF NOT EXISTS {new}{on_cluster} (\n"
        "    event_id      UUID,\n"
        "    dlq_class     LowCardinality(String),\n"
        "    transport     LowCardinality(String),\n"
        "    action        String,\n"
        "    payload       String CODEC(ZSTD(3)),\n"
        "    error_class   String,\n"
        "    error_message String,\n"
        "    created_at    DateTime64(3) CODEC(Delta(8), ZSTD(3))\n"
        ") ENGINE = MergeTree()\n"
        f"PARTITION BY {partition_key}\n"
        "ORDER BY (dlq_class, created_at)\n"
        "TTL created_at + INTERVAL 90 DAY DELETE\n"
        "SETTINGS index_granularity = 8192"
    )
    copy_sql = f"INSERT INTO {new} SELECT * FROM {src}"  # noqa: S608  # names qualified by MigrationPlan
    rename_sql = (
        f"RENAME TABLE {src} TO {old}, {new} TO {src}{on_cluster}"  # noqa: S608  # same
    )

    statements = [create_new_sql, copy_sql, rename_sql]
    return MigrationPlan(
        table_source=table_source,
        table_new=table_new,
        table_old=f"{table_source}_old",
        database=database,
        cluster=cluster,
        create_new_sql=create_new_sql,
        copy_sql=copy_sql,
        rename_sql=rename_sql,
        statements=statements,
    )


def _resolve_confirm(args: argparse.Namespace) -> bool:
    """Confirm flag: True если передан --confirm ИЛИ env CONFIRM=1."""

    if args.confirm:
        return True
    return os.getenv("CONFIRM", "").strip().lower() in {"1", "true", "yes"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI parser — без side-effects."""

    p = argparse.ArgumentParser(
        prog="migrate_dlq_partition",
        description=(
            "Migrate ClickHouse dlq_events to PARTITION BY toYYYYMM(created_at). "
            "Dry-run by default — pass --confirm or set CONFIRM=1 to write."
        ),
    )
    p.add_argument(
        "--ch-url",
        default=os.getenv("CH_URL", "http://localhost:8123"),
        help="ClickHouse URL (env: CH_URL).",
    )
    p.add_argument(
        "--ch-user",
        default=os.getenv("CH_USER", "default"),
        help="ClickHouse user (env: CH_USER).",
    )
    p.add_argument(
        "--ch-password",
        default=os.getenv("CH_PASSWORD", ""),
        help="ClickHouse password (env: CH_PASSWORD).",
    )
    p.add_argument(
        "--database",
        default=os.getenv("CH_DATABASE", "default"),
        help="Database name (env: CH_DATABASE, default 'default').",
    )
    p.add_argument(
        "--cluster",
        default=os.getenv("CH_CLUSTER"),
        help=(
            "Cluster name for ON CLUSTER DDL "
            "(env: CH_CLUSTER). If empty → single-node mode."
        ),
    )
    p.add_argument(
        "--table-source",
        default="dlq_events",
        help="Source table name (default: dlq_events).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help=(
            "Read-only — print plan, do NOT execute DDL. "
            "This is the DEFAULT. Pass --confirm to apply."
        ),
    )
    p.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Required to actually execute DDL. "
            "Env alternative: CONFIRM=1. Overrides --dry-run."
        ),
    )
    p.add_argument(
        "--stats-out",
        type=str,
        default="dlq_partition_migration_stats.json",
        help="Path for migration stats JSON (default: dlq_partition_migration_stats.json).",
    )
    return p.parse_args(argv)


def run_migration(
    args: argparse.Namespace,
    *,
    client_factory: Any = None,
    plan: MigrationPlan | None = None,
) -> int:
    """Запустить миграцию.

    Args:
        args: parsed :func:`parse_args` namespace.
        client_factory: callable ``() → clickhouse_connect client``
            (default: ``clickhouse_connect.get_client``).
            Инъекция для тестов.
        plan: pre-built :class:`MigrationPlan` (default: build via
            :func:`build_ddl_statements`). Инъекция для тестов.

    Returns:
        Exit code (0 = success, 1 = error, 2 = invalid args).
    """
    confirm = _resolve_confirm(args)
    dry_run = not confirm

    if plan is None:
        plan = build_ddl_statements(
            table_source=args.table_source,
            table_new=f"{args.table_source}_new",
            database=args.database,
            cluster=(args.cluster or None),
        )

    started_at = datetime.now(UTC).isoformat()
    logger.info(
        "Migration plan: source=%s new=%s database=%s cluster=%s mode=%s",
        plan.table_source,
        plan.table_new,
        plan.database,
        plan.cluster or "(none)",
        "DRY-RUN" if dry_run else "CONFIRM",
    )
    for idx, stmt in enumerate(plan.statements, 1):
        logger.info("[step %d/%d] %s", idx, len(plan.statements), stmt)

    if dry_run:
        logger.info(
            "Dry-run: NOT executing any DDL. "
            "Pass --confirm or set CONFIRM=1 to apply."
        )
        # Audit trail в stats (даже для dry-run).
        _write_stats(
            args.stats_out,
            {
                "started_at": started_at,
                "mode": "dry-run",
                "plan": {
                    "source": plan.table_source,
                    "new": plan.table_new,
                    "old": plan.table_old,
                    "database": plan.database,
                    "cluster": plan.cluster,
                    "statements": plan.statements,
                },
                "executed": [],
            },
        )
        return 0

    # Confirm path — реальное выполнение.
    if client_factory is None:
        import clickhouse_connect  # type: ignore[import-not-found]

        client_factory = clickhouse_connect.get_client

    try:
        client = client_factory(
            url=args.ch_url,
            username=args.ch_user,
            password=args.ch_password or "",
            database=args.database,
        )
    except Exception as exc:
        logger.error("Failed to create ClickHouse client: %r", exc)
        return 1

    executed: list[str] = []
    try:
        for idx, stmt in enumerate(plan.statements, 1):
            logger.info("[execute %d/%d] %s", idx, len(plan.statements), stmt)
            try:
                client.command(stmt)
                executed.append(stmt)
            except Exception as exc:
                logger.error(
                    "DDL step %d failed: %r\nStatement was:\n%s",
                    idx,
                    exc,
                    stmt,
                )
                _write_stats(
                    args.stats_out,
                    {
                        "started_at": started_at,
                        "mode": "confirm",
                        "plan": {
                            "source": plan.table_source,
                            "new": plan.table_new,
                            "old": plan.table_old,
                            "database": plan.database,
                            "cluster": plan.cluster,
                        },
                        "executed": executed,
                        "failed_step": idx,
                        "failed_stmt": stmt,
                        "error": repr(exc),
                    },
                )
                return 1
    finally:
        try:
            client.close()
        except Exception as exc:
            logger.debug("client.close() raised: %r", exc)

    _write_stats(
        args.stats_out,
        {
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat(),
            "mode": "confirm",
            "plan": {
                "source": plan.table_source,
                "new": plan.table_new,
                "old": plan.table_old,
                "database": plan.database,
                "cluster": plan.cluster,
            },
            "executed": executed,
        },
    )
    logger.info("Migration completed: %d statements executed.", len(executed))
    return 0


def _write_stats(path: str, payload: dict[str, Any]) -> None:
    """Persist migration stats JSON. Failures — non-fatal."""

    import json

    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        logger.info("Stats written to %s", path)
    except OSError as exc:
        logger.warning("Failed to write stats to %s: %r", path, exc)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_args(argv)
    return run_migration(args)


if __name__ == "__main__":
    sys.exit(main())
