"""Restore dev_light DB ← SQLite snapshot (Sprint 9 K2 W8).

Pair к ``snapshot_db.py``. Восстанавливает PG таблицы + Redis keys из
SQLite-файла.

Usage::

    .venv/bin/python tools/dev/restore_db.py \\
        --input .dev_snapshots/baseline.sqlite \\
        --confirm
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def restore_pg_from_sqlite(
    *, pg_engine: object, sqlite_path: Path, truncate_first: bool = True
) -> dict[str, int]:
    """Restore PG tables из SQLite snapshot.

    Args:
        pg_engine: SQLAlchemy sync Engine.
        sqlite_path: snapshot файл.
        truncate_first: если True — TRUNCATE существующих таблиц до restore.

    Returns:
        ``{table_name: rows_restored}``.
    """
    if not sqlite_path.exists():
        raise FileNotFoundError(f"Snapshot file not found: {sqlite_path}")
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_cur = sqlite_conn.cursor()

    pg_tables = [
        name[3:]  # strip "pg_" prefix
        for (name,) in sqlite_cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'pg_%'"
        )
    ]

    counts: dict[str, int] = {}
    from sqlalchemy import text

    with pg_engine.begin() as pg_conn:
        for table in pg_tables:
            sqlite_cur.execute(f"PRAGMA table_info(pg_{table})")
            cols = [row[1] for row in sqlite_cur.fetchall()]
            if not cols:
                continue
            if truncate_first:
                pg_conn.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
            sqlite_cur.execute(f"SELECT * FROM pg_{table}")  # noqa: S608  # admin tool: identifier from CLI args, not user input
            rows = sqlite_cur.fetchall()
            if not rows:
                counts[table] = 0
                continue
            placeholders = ", ".join(f":{c}" for c in cols)
            for row in rows:
                params = dict(zip(cols, row, strict=True))
                # Restore JSON-encoded values
                for k, v in params.items():
                    if isinstance(v, str) and v and v[0] in "[{":
                        try:
                            params[k] = json.loads(v)
                        except json.JSONDecodeError:
                            pass
                pg_conn.execute(
                    text(
                        f"INSERT INTO {table} ({', '.join(cols)}) "  # noqa: S608  # admin tool: identifier from CLI args, not user input
                        f"VALUES ({placeholders})"
                    ),
                    params,
                )
            counts[table] = len(rows)

    sqlite_conn.close()
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore PG ← SQLite snapshot.")
    parser.add_argument(
        "--input", type=Path, required=True, help="путь к SQLite snapshot файлу"
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="подтверждение (без него — dry-run без TRUNCATE)",
    )
    parser.add_argument(
        "--no-truncate",
        action="store_true",
        help="не делать TRUNCATE существующих таблиц",
    )
    args = parser.parse_args(argv)

    if not args.confirm:
        print(
            "DRY RUN: pass --confirm to actually restore. This will TRUNCATE tables.",
            file=sys.stderr,
        )
        return 1

    try:
        from src.backend.infrastructure.database.database import sync_engine
    except ImportError as exc:
        print(f"ERROR: cannot import sync_engine: {exc}", file=sys.stderr)
        return 1
    if sync_engine is None:
        print("ERROR: sync_engine is None (no psycopg2?)", file=sys.stderr)
        return 1

    counts = restore_pg_from_sqlite(
        pg_engine=sync_engine,
        sqlite_path=args.input,
        truncate_first=not args.no_truncate,
    )
    print(f"Restored {len(counts)} tables from {args.input}:")
    for table, n in counts.items():
        print(f"  {table}: {n} rows")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
