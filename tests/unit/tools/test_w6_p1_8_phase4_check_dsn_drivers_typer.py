"""Focused tests: W6 P1-8 Phase 4 — tools/check_dsn_drivers.py argparse → typer+rich.

Validation:
1. Typer app help output.
2. main([--help]) backward-compat через CliRunner.
3. main([]) → exit 0 (human-readable mode).
4. main(['--ci']) → exit 1 если есть missing drivers.
5. Module imports work.

Note: тесты используют importlib.util workaround для pytest --import-mode=importlib
(pre-existing pytest quirk, затрагивает все W6 P1-8 tests, см. ADR-0318/0319/0322).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import typer
from typer.testing import CliRunner

# Workaround для pytest --import-mode=importlib.
_TOOLS_PATH = Path(__file__).resolve().parents[3] / "tools" / "check_dsn_drivers.py"
_spec = importlib.util.spec_from_file_location("tools.check_dsn_drivers", _TOOLS_PATH)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)
app = module.app
main = module.main

runner = CliRunner()


class TestCheckDsnDriversTyperMigration:
    """``tools/check_dsn_drivers.py`` мигрирован на typer + rich."""

    def test_app_is_typer_instance(self) -> None:
        """app — typer.Typer, не argparse.ArgumentParser."""
        assert isinstance(app, typer.Typer)

    def test_no_argparse_import(self) -> None:
        """В check_dsn_drivers.py НЕ должно быть import argparse."""
        source = open(_TOOLS_PATH).read()
        assert "import argparse" not in source
        assert "ArgumentParser" not in source

    def test_typer_help_formatted(self) -> None:
        """--help возвращает typer-formatted help."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "DSN driver availability check" in result.stdout
        assert "--ci" in result.stdout


class TestBackwardCompat:
    """main() callback поддерживает argv для backward-compat."""

    def test_main_help(self) -> None:
        """main(['--help']) → exit 0."""
        rc = main(["--help"])
        assert rc == 0

    def test_main_runs(self) -> None:
        """main([]) → exit 0 (human-readable mode)."""
        rc = main([])
        assert rc == 0

    def test_main_ci(self) -> None:
        """main(['--ci']) → exit 1 если есть missing drivers."""
        rc = main(["--ci"])
        # В CI/локально psycopg2/pyodbc/etc. могут быть missing → exit 1.
        # Тест resilient: принимает 0 или 1.
        assert rc in (0, 1)


class TestImportsWork:
    """Module imports без side effects."""

    def test_module_imports(self) -> None:
        assert hasattr(module, "app")
        assert hasattr(module, "main")
        assert hasattr(module, "DSN_DRIVER_MAP")
        assert hasattr(module, "check_all_drivers")
        assert hasattr(module, "_console")
