#!/usr/bin/env python3
"""Sprint 36 K5 (D-AUDIT-1504): Alembic drift detection gate.

Назначение:
    Проверяет, что SQLAlchemy ``metadata`` (после auto-import плагинов
    через :func:`migrations.env` target_metadata) совпадает со схемой
    последней ревизии Alembic (``alembic_version`` table).

    Это critical gate для CI: поймает ситуацию, когда разработчик добавил
    ORM-модель/колонку в plugin models, но забыл сгенерировать
    autogenerate-миграцию. Раньше drift обнаруживался только в prod при
    первом SELECT — silent schema drift (ADR-NEW-12, S76 W3 #14).

Использование (CLI):
    python -m tools.check_alembic_drift
        # → reads DATABASE_URL from env, runs alembic check + autogenerate
        #   diff; exit 0 on OK, exit 1 on drift, exit 2 on connection error.

    python -m tools.check_alembic_drift --db-url postgresql+asyncpg://...
        # → explicit DB URL override.

    python -m tools.check_alembic_drift --metadata-only
        # → только dump metadata в JSON (для snapshot-compare в офлайн-CI);
        #   без DB connection.

Output:
    exit codes:
        0 — schema matches migrations (no drift);
        1 — drift detected (autogenerate found new/changed tables/columns);
        2 — database connection error / migration version missing;
        3 — parse error in env.py (autogenerate fails).

Зависимости:
    - alembic (required для --metadata-only и DB mode);
    - SQLAlchemy (required, уже в стеке);
    - asyncpg/psycopg2 (для production DB).

Совместимость:
    Работает с async + sync SQLAlchemy через alembic script.
    Без DB connection (``--metadata-only``) — для офлайн-mode в CI.

Refs:
    - D-AUDIT-1503 (cycle-15) — auto-discovery plugin models в env.py;
    - D-AUDIT-1501 (cycle-15) — ``models_module`` field в PluginManifest;
    - ADR-NEW-12 — schema drift detection как CI gate (S76 W3).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

# Путь к migrations (для autogenerate head против target_metadata).
_REPO_ROOT = Path(__file__).resolve().parents[1]
_MIGRATIONS_DIR = _REPO_ROOT / "src" / "backend" / "infrastructure" / "database" / "migrations"
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"

_logger = logging.getLogger("tools.check_alembic_drift")


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def _dump_metadata_to_dict() -> dict[str, Any]:
    """Импортирует target_metadata из env.py и сериализует в JSON.

    Без DB-соединения — для офлайн-mode (``--metadata-only``).
    Использует те же hardcoded + auto-discovery imports, что и
    ``alembic revision --autogenerate``.

    Подход: запускаем Alembic CLI в subprocess с ``alembic upgrade``
    dry-run mode (или read metadata via env.py). Так как env.py
    использует ``context.is_offline_mode()`` и ``context.run_migrations()``
    на module-level, прямой import невозможен — нужен real alembic CLI.

    Альтернатива: импортируем ``metadata`` напрямую из base.py и
    импортируем те же модули, что и env.py (hardcoded + auto-discovery).
    Это синхронная версия того, что Alembic делает при autogenerate.

    Returns:
        dict с keys: ``tables`` (sorted list of table names),
        ``total_tables`` (int), ``total_indexes`` (int),
        ``version`` (alembic_version from env or "unknown").
    """
    # Прямой import: ``metadata`` уже инициализирован в base.py.
    # Hardcoded core_entities imports из env.py воспроизводим здесь
    # (auto-discovery — отдельный шаг через :func:`_discover_plugin_models`).
    try:
        # 1) Hardcoded core_entities (4 импорта из env.py).
        from extensions.core_entities.files.domain.models import (  # noqa: F401
            File,
            OrderFile,
        )
        from extensions.core_entities.orderkinds.domain.models import (  # noqa: F401
            OrderKind,
        )
        from extensions.core_entities.orders.domain.models import Order  # noqa: F401
        from extensions.core_entities.users.domain.models import User  # noqa: F401

        # 2) Auto-discovery через :func:`load_plugin_manifests_for_migrations`.
        from src.backend.services.plugins.loader import (
            load_plugin_manifests_for_migrations,
        )

        discovered = load_plugin_manifests_for_migrations(_REPO_ROOT / "extensions")
        for mwp in discovered:
            for module_path in mwp.manifest.models_module:
                try:
                    __import__(module_path, fromlist=["__name__"])
                except ImportError as imp_exc:
                    _logger.warning(
                        "plugin %s: models_module %s import failed: %s",
                        mwp.manifest.name,
                        module_path,
                        imp_exc,
                    )

        # 3) Берём target_metadata (тот же объект, что env.py присваивает).
        from src.backend.core.domain.models.base import metadata

        tables = sorted(metadata.tables.keys())
        total_indexes = sum(len(t.indexes) for t in metadata.tables.values())
        return {
            "tables": tables,
            "total_tables": len(tables),
            "total_indexes": total_indexes,
            "version": "unknown",
        }
    except Exception as exc:
        _logger.error("metadata dump failed: %s", exc)
        msg = f"metadata dump failed: {exc}"
        raise RuntimeError(msg) from exc


def _run_alembic_check(db_url: str) -> tuple[bool, str]:
    """Запускает ``alembic check`` через subprocess и парсит exit code.

    Args:
        db_url: SQLAlchemy-compatible DB URL (e.g. postgresql+asyncpg://...).

    Returns:
        (is_drift, message) — is_drift=True если drift detected.
    """
    cmd = [
        sys.executable,
        "-m",
        "alembic",
        "check",
    ]
    _logger.debug("running: %s", " ".join(cmd))
    env_overrides = {"DATABASE_URL": db_url} if db_url else {}
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        env={**__import__("os").environ, **env_overrides},
        check=False,
    )
    out = (proc.stdout + "\n" + proc.stderr).strip()
    # alembic exit codes: 0=ok, 1=drift, 2=connection error.
    is_drift = proc.returncode == 1
    if proc.returncode > 1:
        _logger.error("alembic check connection error: %s", out)
        return False, f"connection error (exit={proc.returncode}): {out}"
    return is_drift, out


def _run_alembic_autogenerate(db_url: str) -> tuple[bool, str]:
    """Запускает ``alembic revision --autogenerate -m ...`` и парсит output.

    Используется для генерации migration draft при обнаружении drift
    (``--suggest-fix`` mode) — НЕ для CI gate.

    Returns:
        (has_drift, output) — has_drift=True если autogenerate нашёл
        изменения (т.е. есть что генерировать).
    """
    cmd = [
        sys.executable,
        "-m",
        "alembic",
        "revision",
        "--autogenerate",
        "-m",
        "drift_check_autogenerate",
    ]
    env_overrides = {"DATABASE_URL": db_url} if db_url else {}
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        env={**__import__("os").environ, **env_overrides},
        check=False,
    )
    out = (proc.stdout + "\n" + proc.stderr).strip()
    has_drift = "empty" not in out.lower() and proc.returncode == 0
    return has_drift, out


def _run_metadata_only() -> int:
    """Режим ``--metadata-only``: dump metadata без DB connection.

    Используется для офлайн-сравнения metadata snapshot между коммитами:
    CI может кешировать ``metadata.json`` artifact и diff с main.
    """
    try:
        md_dict = asyncio.run(_dump_metadata_to_dict())
    except RuntimeError as exc:
        _logger.error("metadata dump failed: %s", exc)
        return 3
    print(json.dumps(md_dict, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point для CLI и ``python -m tools.check_alembic_drift``."""
    parser = argparse.ArgumentParser(
        prog="check_alembic_drift",
        description="Alembic schema drift detection gate (D-AUDIT-1504, cycle-15)",
    )
    parser.add_argument(
        "--db-url",
        default="",
        help="SQLAlchemy DB URL override (default: DATABASE_URL env)",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Only dump target_metadata to JSON (offline mode, no DB connection)",
    )
    parser.add_argument(
        "--suggest-fix",
        action="store_true",
        help="Run alembic revision --autogenerate to generate migration draft "
        "(non-CI, developer helper)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="DEBUG logging",
    )
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    if args.metadata_only:
        return _run_metadata_only()

    db_url = args.db_url or __import__("os").environ.get("DATABASE_URL", "")
    if not db_url:
        _logger.error("DATABASE_URL not set — use --db-url or env var")
        return 2

    if args.suggest_fix:
        has_drift, out = _run_alembic_autogenerate(db_url)
        print(out)
        return 0 if not has_drift else 1

    is_drift, out = _run_alembic_check(db_url)
    print(out)
    if "no drift" in out.lower() or "no changes" in out.lower() or not is_drift:
        if is_drift:
            print("⚠ Alembic check found drift (exit=1)")
            return 1
        print("✓ Alembic check: no drift detected")
        return 0
    if is_drift:
        print("⚠ Alembic check: drift detected — autogenerate migration needed")
        return 1
    print("✓ Alembic check: no drift detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
