"""Tests for tools/check_dsn_drivers.py (S106 W7).

Verifies DSN driver availability check tool:
- All DatabaseTypeChoices have driver mappings
- Sync + async paired (e.g. mssql → pyodbc + aioodbc)
- Tool runs in human-readable + --ci mode
- Exit code 1 если any driver missing (--ci mode)
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

# Load check_dsn_drivers module via spec (tools/ — не Python package,
# не имеет __init__.py; используем file-based import)
_tools_dir = Path(__file__).resolve().parents[3] / "tools"
_check_file = _tools_dir / "check_dsn_drivers.py"
_spec = importlib.util.spec_from_file_location("check_dsn_drivers", _check_file)
_check_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_check_mod)
DSN_DRIVER_MAP = _check_mod.DSN_DRIVER_MAP
check_all_drivers = _check_mod.check_all_drivers
render_human = _check_mod.render_human

import pytest


def test_dsn_map_covers_all_types() -> None:
    """DSN_DRIVER_MAP покрывает все DatabaseTypeChoices."""
    # Импортируем через sys.path (V22 layout)
    from src.backend.core.enums.database import DatabaseTypeChoices

    for db_type in DatabaseTypeChoices:
        assert db_type.value in DSN_DRIVER_MAP, (
            f"DSN_DRIVER_MAP missing entry for {db_type.value}"
        )


def test_dsn_map_has_sync_async_pair() -> None:
    """Каждый type имеет (sync, async) кортеж из 2-х driver names."""
    for db_type, drivers in DSN_DRIVER_MAP.items():
        assert isinstance(drivers, tuple) and len(drivers) == 2, (
            f"{db_type}: expected tuple of 2 drivers, got {drivers}"
        )
        sync, async_ = drivers
        assert sync and async_, f"{db_type}: empty driver name"
        # Имена должны быть valid Python identifiers
        assert sync.replace("_", "").isalnum(), f"{db_type}: sync={sync}"
        assert async_.replace("_", "").isalnum(), f"{db_type}: async={async_}"


def test_dsn_map_specific_entries() -> None:
    """Конкретные entries для S104 W3 added types (mssql/mysql/db2)."""
    assert DSN_DRIVER_MAP["mssql"] == ("pyodbc", "aioodbc")
    assert DSN_DRIVER_MAP["mysql"] == ("pymysql", "aiomysql")
    assert DSN_DRIVER_MAP["db2"] == ("ibm_db_sa", "ibm_db")


def test_check_all_drivers_returns_results() -> None:
    """check_all_drivers возвращает list of DriverCheckResult."""
    results = check_all_drivers()
    assert len(results) == len(DSN_DRIVER_MAP)
    for r in results:
        assert r.db_type in DSN_DRIVER_MAP
        assert r.sync_driver
        assert r.async_driver
        assert isinstance(r.sync_available, bool)
        assert isinstance(r.async_available, bool)


def test_render_human_output() -> None:
    """render_human возвращает non-empty readable report."""
    results = check_all_drivers()
    text = render_human(results)
    assert "DSN driver availability" in text
    assert "=" * 60 in text or "===" in text
    # Per-type line
    for r in results:
        assert r.db_type in text
        assert r.sync_driver in text


def test_tool_runs_in_human_mode() -> None:
    """Без --ci: human-readable + exit 0 (no CI gate)."""
    tools_dir = Path(__file__).resolve().parents[3] / "tools"
    check_file = tools_dir / "check_dsn_drivers.py"
    result = subprocess.run(
        [sys.executable, str(check_file)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "DSN driver availability" in result.stdout


def test_tool_runs_in_ci_mode() -> None:
    """С --ci: exit 0 если all available, exit 1 если any missing."""
    tools_dir = Path(__file__).resolve().parents[3] / "tools"
    check_file = tools_dir / "check_dsn_drivers.py"
    result = subprocess.run(
        [sys.executable, str(check_file), "--ci"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    # В текущем venv: psycopg2, pyodbc, aioodbc, pymysql, aiomysql, ibm_db_sa,
    # ibm_db, cx_Oracle, oracledb — все optional deps, не установлены.
    # Expected: exit 1 (at least one missing)
    assert result.returncode == 1
    assert "MISSING drivers" in result.stdout or "missing" in result.stdout.lower()
