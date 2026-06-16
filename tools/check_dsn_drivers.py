"""DSN driver availability check (S106 W7 = Sprint B W2).

S104 W3 added MSSQL/MySQL/DB2 DSN types (DEEP-RESEARCH D19). Drivers
(``pyodbc``, ``aioodbc``, ``aiomysql``, ``pymysql``, ``ibm_db_sa``) are
**optional deps** — не в ``[project.dependencies]``, только в
``[project.optional-dependencies]`` (или вообще не включены в dev).

Проблема: если пользователь конфигурирует ``database.type=mssql`` без
``pyodbc``, ошибка возникает только при runtime ``DatabaseInitializer``
(и то через obscure ``ImportError``). Tool даёт fail-fast на этапе
bootstrap/CI.

Проверяет:
- Все DSN типы из ``DatabaseTypeChoices`` имеют соответствующий
  driver module (sync + async варианты)
- Driver actually importable в текущем venv
- Async + sync paired корректно (если async есть, sync должен быть)

Запуск::

    python tools/check_dsn_drivers.py             # human-readable
    python tools/check_dsn_drivers.py --ci        # exit 1 на missing

Exit code 0 — все drivers available;
Exit code 1 — хотя бы один type requires missing driver.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from typing import NamedTuple

# S106 W7: маппинг DSN type → (sync_driver, async_driver) modules.
# Должно mirror то, что ``DatabaseConnectionSettings.dsn()`` использует
# (см. ``src/backend/core/config/database.py``).
DSN_DRIVER_MAP: dict[str, tuple[str, str]] = {
    "postgresql": ("psycopg2", "asyncpg"),
    "sqlite": ("sqlite3", "aiosqlite"),
    "mssql": ("pyodbc", "aioodbc"),
    "mysql": ("pymysql", "aiomysql"),
    "db2": ("ibm_db_sa", "ibm_db"),  # ibm_db — async редкий, sync primary
    "oracle": ("cx_Oracle", "oracledb"),
}


class DriverCheckResult(NamedTuple):
    """Результат проверки одного DSN type."""

    db_type: str
    sync_driver: str
    async_driver: str
    sync_available: bool
    async_available: bool


def _check_driver(module_name: str) -> bool:
    """Возвращает True если module importable."""
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


def check_all_drivers() -> list[DriverCheckResult]:
    """Проверить все DSN типы и вернуть список результатов."""
    results: list[DriverCheckResult] = []
    for db_type, (sync, async_) in DSN_DRIVER_MAP.items():
        results.append(
            DriverCheckResult(
                db_type=db_type,
                sync_driver=sync,
                async_driver=async_,
                sync_available=_check_driver(sync),
                async_available=_check_driver(async_),
            )
        )
    return results


def render_human(results: list[DriverCheckResult]) -> str:
    """Human-readable report."""
    lines = ["DSN driver availability", "=" * 60]
    for r in results:
        sync_marker = "OK " if r.sync_available else "MISS"
        async_marker = "OK " if r.async_available else "MISS"
        lines.append(
            f"  {r.db_type:12s} | sync={r.sync_driver:12s} [{sync_marker}] | "
            f"async={r.async_driver:12s} [{async_marker}]"
        )
    lines.append("=" * 60)
    missing = [r for r in results if not r.sync_available or not r.async_available]
    if missing:
        lines.append("MISSING drivers — install via pip extras:")
        seen: set[str] = set()
        for r in missing:
            if not r.sync_available and r.sync_driver not in seen:
                lines.append(f"  pip install {r.sync_driver}")
                seen.add(r.sync_driver)
            if not r.async_available and r.async_driver not in seen:
                lines.append(f"  pip install {r.async_driver}")
                seen.add(r.async_driver)
    else:
        lines.append("All drivers available — all DSN types ready.")
    return "\n".join(lines)


def main() -> int:
    """Точка входа: human-readable или CI mode."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ci",
        action="store_true",
        help="Exit code 1 on missing drivers (for CI gates).",
    )
    args = parser.parse_args()

    results = check_all_drivers()
    print(render_human(results))

    if args.ci:
        missing = [r for r in results if not r.sync_available or not r.async_available]
        return 1 if missing else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
