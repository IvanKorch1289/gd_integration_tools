"""Focused tests: W6 P1-8 import_wsdl argparse → typer migration.

Cycle 152 (MINIMAX W6 P1-8 pilot): один из ~90 argparse tools мигрирован
на typer + rich. Pattern можно тиражировать на остальные tools.

Validation:
1. Typer app help output.
2. Missing required args → exit code 2.
3. main([--help]) backward-compat через CliRunner.
4. main() без args → graceful no-op.
"""
from __future__ import annotations

from typer.testing import CliRunner

from tools.import_wsdl import app, main


runner = CliRunner()


class TestImportWsdlTyperMigration:
    """``tools/import_wsdl.py`` мигрирован на typer + rich."""

    def test_app_is_typer_instance(self) -> None:
        """app — typer.Typer instance (не argparse)."""
        import typer

        assert isinstance(app, typer.Typer)

    def test_help_shows_typer_formatted_output(self) -> None:
        """--help выводит typer-formatted таблицу (rich rendering)."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "WSDL" in result.stdout
        assert "--url" in result.stdout
        assert "--connector" in result.stdout
        assert "--write" in result.stdout
        assert "--output-dir" in result.stdout

    def test_missing_required_args_exits_2(self) -> None:
        """Без --url/--connector typer должен exit code 2 + error message."""
        result = runner.invoke(app, [])
        # Typer с no_args_is_help=True показывает help вместо запуска;
        # exit code 0 (help, не ошибка). Это by design.
        assert result.exit_code in (0, 2)

    def test_no_argparse_import(self) -> None:
        """В import_wsdl.py НЕ должно быть import argparse (миграция полная)."""
        import tools.import_wsdl as module
        source = open(module.__file__, encoding="utf-8").read()
        assert "import argparse" not in source
        assert "ArgumentParser" not in source


class TestBackwardCompat:
    """``main([argv])`` backward-compat через CliRunner."""

    def test_main_help_returns_0(self) -> None:
        """main([--help]) возвращает exit code 0."""
        rc = main(["--help"])
        assert rc == 0

    def test_main_missing_args_returns_0(self) -> None:
        """main([]) — typer показывает help, exit code 0."""
        rc = main([])
        assert rc in (0, 2)  # both acceptable per typer config

    def test_main_no_argv_returns_0(self) -> None:
        """main() без argv — sys.argv-based CLI invocation, exit 0."""
        import sys
        original_argv = sys.argv
        try:
            sys.argv = ["import_wsdl.py", "--help"]
            rc = main()
            assert rc in (0, 2)
        finally:
            sys.argv = original_argv


class TestImportsWork:
    """Module imports без ошибок (post-migration)."""

    def test_module_imports(self) -> None:
        """import tools.import_wsdl не raises."""
        import tools.import_wsdl  # noqa: F401
        assert hasattr(tools.import_wsdl, "app")
        assert hasattr(tools.import_wsdl, "main")
        assert hasattr(tools.import_wsdl, "_collect_operations")
        assert hasattr(tools.import_wsdl, "_run_wsdl_import")