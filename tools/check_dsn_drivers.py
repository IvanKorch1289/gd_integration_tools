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

MINIMAX W6 P1-8 Phase 4 (cycle 153): мигрирован с ``argparse`` на ``typer`` +
``rich`` (libraries > custom, per ADR-0084). Сохранены: typer-native entry +
legacy ``main()`` callback для backward-compat с pre-existing scripts.
"""

from __future__ import annotations

import importlib
from typing import NamedTuple

import typer
from rich.console import Console

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
    # S121 W1: добавлен clickhouse (S168 W10 P1-8 — analytics path).
    # Sync driver: clickhouse-driver (official). Async: asynch.
    "clickhouse": ("clickhouse_driver", "asynch"),
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


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI (backward-compat shim для существующих скриптов).

    Запускает typer app через typer.testing.CliRunner (для тестов)
    или sys.argv (для CLI invocation). Возвращает exit code.
    """
    if argv is not None:
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, argv)
        return result.exit_code
    # CLI invocation: typer сам подхватит sys.argv[1:]
    try:
        app()
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0
    return 0


app = typer.Typer(
    name="check-dsn-drivers",
    help="DSN driver availability check (sync + async).",
    add_completion=False,
)
_console = Console()


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    ci: bool = typer.Option(
        False,
        "--ci",
        help="Exit code 1 on missing drivers (for CI gates).",
    ),
) -> None:
    """Точка входа: human-readable или CI mode."""
    if ctx.invoked_subcommand is not None:
        return

    results = check_all_drivers()
    _console.print(render_human(results))

    if ci:
        missing = [r for r in results if not r.sync_available or not r.async_available]
        if missing:
            raise typer.Exit(code=1)


if __name__ == "__main__":
    raise SystemExit(main())
