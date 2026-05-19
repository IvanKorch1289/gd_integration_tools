"""Snapshot dev_light DB → SQLite file (Sprint 9 K2 W8).

Цель: сохранить состояние PG (dev_light схема) + Redis (cache snapshot)
в один SQLite-файл для:

* быстрый restore локального окружения после ``rm -rf .venv``;
* shareable seed-data между разработчиками;
* CI-snapshot fixture для integration tests.

Usage::

    .venv/bin/python tools/dev/snapshot_db.py \\
        --output .dev_snapshots/baseline.sqlite \\
        --include-tables orders,users,routes

Format snapshot.sqlite:

* metadata table — version + timestamp.
* one table per source table (PG → SQLite copy).
* redis_cache table — key/value/ttl_sec dump.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path


def snapshot_pg_to_sqlite(
    *,
    pg_engine: object,
    sqlite_path: Path,
    include_tables: list[str] | None = None,
) -> dict[str, int]:
    """Копирует таблицы из PG в SQLite-файл.

    Args:
        pg_engine: SQLAlchemy AsyncEngine.
        sqlite_path: целевой SQLite файл.
        include_tables: список таблиц для копирования (None — все public).

    Returns:
        ``{table_name: row_count}``.
    """
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sqlite_path)
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS metadata ("
        "key TEXT PRIMARY KEY, value TEXT)"
    )
    cursor.execute(
        "INSERT OR REPLACE INTO metadata VALUES (?, ?)",
        ("snapshot_version", "1.0"),
    )
    cursor.execute(
        "INSERT OR REPLACE INTO metadata VALUES (?, ?)",
        ("created_at", str(time.time())),
    )

    counts: dict[str, int] = {}
    tables = include_tables or _list_pg_tables(pg_engine)
    for table in tables:
        rows = _select_all(pg_engine, table)
        if not rows:
            counts[table] = 0
            continue
        cols = list(rows[0].keys())
        cursor.execute(f"DROP TABLE IF EXISTS pg_{table}")
        col_defs = ", ".join(f'"{c}" TEXT' for c in cols)
        cursor.execute(f"CREATE TABLE pg_{table} ({col_defs})")
        placeholders = ", ".join("?" for _ in cols)
        values = [
            tuple(
                json.dumps(row[c]) if isinstance(row[c], (dict, list)) else row[c]
                for c in cols
            )
            for row in rows
        ]
        cursor.executemany(
            f"INSERT INTO pg_{table} VALUES ({placeholders})", values
        )
        counts[table] = len(rows)

    conn.commit()
    conn.close()
    return counts


def snapshot_redis_to_sqlite(
    *,
    redis_client: object,
    sqlite_path: Path,
    key_pattern: str = "*",
) -> int:
    """Дамп Redis ключей в snapshot.

    Returns:
        Число сохранённых keys.
    """
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sqlite_path)
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS redis_cache ("
        "key TEXT PRIMARY KEY, value BLOB, ttl_sec INTEGER)"
    )

    # Используем синхронный путь — это dev-инструмент, async overhead не нужен.
    count = 0
    # redis.scan_iter — для production-redis-py, для AsyncRedis fallback
    scan = getattr(redis_client, "scan_iter", None)
    if scan is None:
        conn.close()
        return 0

    for key in scan(key_pattern):
        value = redis_client.get(key)
        ttl = redis_client.ttl(key)
        cursor.execute(
            "INSERT OR REPLACE INTO redis_cache VALUES (?, ?, ?)",
            (key.decode() if isinstance(key, bytes) else key, value, ttl),
        )
        count += 1

    conn.commit()
    conn.close()
    return count


def _list_pg_tables(pg_engine: object) -> list[str]:
    """SQLAlchemy 2.x inspection."""
    from sqlalchemy import inspect

    insp = inspect(pg_engine)
    return [t for t in insp.get_table_names() if not t.startswith("_")]


def _select_all(pg_engine: object, table: str) -> list[dict]:
    from sqlalchemy import text

    with pg_engine.connect() as conn:
        result = conn.execute(text(f"SELECT * FROM {table} LIMIT 10000"))
        return [dict(row._mapping) for row in result]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Snapshot dev_light → SQLite.")
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="путь к SQLite snapshot файлу",
    )
    parser.add_argument(
        "--include-tables",
        default="",
        help="comma-separated имена таблиц (default — все public)",
    )
    parser.add_argument(
        "--skip-redis",
        action="store_true",
        help="не дампить Redis (только PG)",
    )
    args = parser.parse_args(argv)

    tables = [t.strip() for t in args.include_tables.split(",") if t.strip()]
    print(f"Snapshot to: {args.output}")
    try:
        from src.backend.infrastructure.database.database import sync_engine
    except ImportError as exc:
        print(f"ERROR: cannot import sync_engine: {exc}", file=sys.stderr)
        return 1
    if sync_engine is None:
        print("ERROR: sync_engine is None (no psycopg2?)", file=sys.stderr)
        return 1

    counts = snapshot_pg_to_sqlite(
        pg_engine=sync_engine,
        sqlite_path=args.output,
        include_tables=tables or None,
    )
    print(f"PG tables dumped: {len(counts)}")
    for table, n in counts.items():
        print(f"  {table}: {n} rows")
    print(f"OK: snapshot written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
