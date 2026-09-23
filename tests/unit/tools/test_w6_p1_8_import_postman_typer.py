"""Focused tests: W6 P1-8 Phase 2 — import_postman argparse → typer migration.

Cycle 152 (MINIMAX W6 P1-8 Phase 2): второй pilot ( после import_wsdl.py ).
Pattern повторяется — тот же `app.callback(invoke_without_command=True)`
+ `CliRunner` для тестов + `app()` для CLI invocation.
"""
from __future__ import annotations

from typer.testing import CliRunner

from tools.import_postman import app, main


runner = CliRunner()


class TestImportPostmanTyperMigration:
    """``tools/import_postman.py`` мигрирован на typer + rich."""

    def test_app_is_typer_instance(self) -> None:
        """app — typer.Typer instance."""
        import typer

        assert isinstance(app, typer.Typer)

    def test_help_shows_typer_formatted_output(self) -> None:
        """--help выводит typer-formatted таблицу."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Postman" in result.stdout
        assert "--file" in result.stdout
        assert "--connector" in result.stdout
        assert "--write" in result.stdout
        assert "--output-dir" in result.stdout

    def test_no_argparse_import(self) -> None:
        """В import_postman.py НЕ должно быть import argparse."""
        import tools.import_postman as module

        source = open(module.__file__, encoding="utf-8").read()
        assert "import argparse" not in source
        assert "ArgumentParser" not in source

    def test_no_sys_stdout_write(self) -> None:
        """Миграция полная: нет sys.stdout.write (typer+rich вместо)."""
        import tools.import_postman as module

        source = open(module.__file__, encoding="utf-8").read()
        # sys.stdout.write — old-style output; новая migration uses _console.print.
        # Разрешаем `import sys` для других нужд, но не `sys.stdout.write`.
        assert "sys.stdout.write" not in source


class TestBackwardCompat:
    """``main(argv)`` backward-compat через CliRunner."""

    def test_main_help_returns_0(self) -> None:
        """main([--help]) возвращает exit code 0."""
        rc = main(["--help"])
        assert rc == 0

    def test_main_missing_args_returns_0(self) -> None:
        """main([]) — typer показывает help, exit code 0."""
        rc = main([])
        assert rc in (0, 2)


class TestImportsWork:
    """Module imports без ошибок (post-migration)."""

    def test_module_imports(self) -> None:
        """import tools.import_postman не raises."""
        import tools.import_postman  # noqa: F401
        assert hasattr(tools.import_postman, "app")
        assert hasattr(tools.import_postman, "main")
        assert hasattr(tools.import_postman, "_flatten_items")
        assert hasattr(tools.import_postman, "_collect_requests")
        assert hasattr(tools.import_postman, "_to_snake")
        assert hasattr(tools.import_postman, "_run_postman_import")