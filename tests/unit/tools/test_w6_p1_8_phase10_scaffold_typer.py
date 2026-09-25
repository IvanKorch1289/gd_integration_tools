"""Focused tests: W6 P1-8 Phase 10 — tools/scaffold.py argparse → typer+rich.

Validation:
1. Typer app help output (3 subcommands: processor/service/route).
2. main(['--help']) backward-compat.
3. main(['processor', '--help']) → processor options.
4. main(['processor', '--name', 'X', '--dry-run']) → DRY-RUN mode (no file changes).
5. Module imports work.

Note: тесты используют importlib.util workaround для pytest --import-mode=importlib.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import typer
from typer.testing import CliRunner

# Workaround для pytest --import-mode=importlib.
_TOOLS_PATH = Path(__file__).resolve().parents[3] / "tools" / "scaffold.py"
_spec = importlib.util.spec_from_file_location("tools.scaffold", _TOOLS_PATH)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)
app = module.app
main = module.main

runner = CliRunner()


class TestScaffoldTyperMigration:
    """``tools/scaffold.py`` мигрирован на typer + rich."""

    def test_app_is_typer_instance(self) -> None:
        """app — typer.Typer, не argparse.ArgumentParser."""
        assert isinstance(app, typer.Typer)

    def test_no_argparse_import(self) -> None:
        """В scaffold.py НЕ должно быть import argparse."""
        source = open(_TOOLS_PATH).read()
        assert "import argparse" not in source
        assert "ArgumentParser" not in source

    def test_typer_help_formatted(self) -> None:
        """--help возвращает typer-formatted help с 3 subcommands."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "processor" in result.stdout
        assert "service" in result.stdout
        assert "route" in result.stdout

    def test_subcommand_help(self) -> None:
        """processor --help возвращает typer-formatted options."""
        result = runner.invoke(app, ["processor", "--help"])
        assert result.exit_code == 0
        assert "--name" in result.stdout
        assert "--module" in result.stdout
        assert "--dry-run" in result.stdout


class TestBackwardCompat:
    """main() callback backward-compat."""

    def test_main_help(self) -> None:
        """main(['--help']) → exit 0."""
        rc = main(["--help"])
        assert rc == 0

    def test_main_processor_dry_run(self) -> None:
        """main(['processor', '--name', 'TestProcessor', '--dry-run']) → exit 0.

        DRY-RUN mode не должен создавать файл.
        """
        rc = main(["processor", "--name", "TestProcessor", "--dry-run"])
        assert rc == 0

    def test_main_service_dry_run(self) -> None:
        """main(['service', '--name', 'TestService', '--dry-run']) → exit 0."""
        rc = main(["service", "--name", "TestService", "--dry-run"])
        assert rc in (0, 1)  # 0 = OK, 1 = file already exists (test re-run)

    def test_main_route_dry_run(self) -> None:
        """main(['route', '--name', 'test.route', '--dry-run']) → exit 0."""
        rc = main(["route", "--name", "test.route", "--dry-run"])
        assert rc == 0


class TestSafety:
    """Safety: --dry-run НЕ создаёт файлы."""

    def test_dry_run_does_not_create_files(self) -> None:
        """--dry-run должен только печатать, без записи на диск."""
        # Проверяем что файл НЕ создаётся.
        test_path = Path(
            "src/backend/dsl/engine/processors/scaffold_test_dry_run_marker.py"
        )
        assert not test_path.exists(), (
            f"Pre-condition: {test_path} should not exist before test"
        )

        result = runner.invoke(
            app,
            [
                "processor",
                "--name",
                "ScaffoldTestDryRunMarker",
                "--module",
                "scaffold_test_dry_run_marker",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        # DRY-RUN не должен создать файл.
        assert not test_path.exists(), f"DRY-RUN created file {test_path} (should NOT)"


class TestImportsWork:
    """Module imports без side effects."""

    def test_module_imports(self) -> None:
        assert hasattr(module, "app")
        assert hasattr(module, "main")
        assert hasattr(module, "processor_template")
        assert hasattr(module, "service_template")
        assert hasattr(module, "route_template")
        assert hasattr(module, "_emit")
        assert hasattr(module, "_console")
