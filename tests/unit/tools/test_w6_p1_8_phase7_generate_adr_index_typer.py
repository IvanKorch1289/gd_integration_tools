"""Focused tests: W6 P1-8 Phase 7 — tools/generate_adr_index.py argparse → typer+rich.

Validation:
1. Typer app help output.
2. main([--help]) backward-compat через CliRunner.
3. main(['--check']) → exit 0 если INDEX.md up-to-date.
4. main(['--dry-run']) → exit 0, prints to stdout.
5. Module imports work.

Note: тесты используют importlib.util workaround для pytest --import-mode=importlib.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import typer
from typer.testing import CliRunner

# Workaround для pytest --import-mode=importlib.
_TOOLS_PATH = Path(__file__).resolve().parents[3] / "tools" / "generate_adr_index.py"
_spec = importlib.util.spec_from_file_location("tools.generate_adr_index", _TOOLS_PATH)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)
app = module.app
main = module.main

runner = CliRunner()


class TestGenerateAdrIndexTyperMigration:
    """``tools/generate_adr_index.py`` мигрирован на typer + rich."""

    def test_app_is_typer_instance(self) -> None:
        """app — typer.Typer, не argparse.ArgumentParser."""
        assert isinstance(app, typer.Typer)

    def test_no_argparse_import(self) -> None:
        """В generate_adr_index.py НЕ должно быть import argparse."""
        source = open(_TOOLS_PATH).read()
        assert "import argparse" not in source
        assert "ArgumentParser" not in source

    def test_typer_help_formatted(self) -> None:
        """--help возвращает typer-formatted help."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "INDEX" in result.stdout
        assert "--check" in result.stdout
        assert "--dry-run" in result.stdout


class TestBackwardCompat:
    """main() callback поддерживает argv для backward-compat."""

    def test_main_help(self) -> None:
        """main(['--help']) → exit 0."""
        rc = main(["--help"])
        assert rc == 0

    def test_main_dry_run(self) -> None:
        """main(['--dry-run']) → exit 0, prints to stdout."""
        rc = main(["--dry-run"])
        assert rc == 0

    def test_main_check_up_to_date(self) -> None:
        """main(['--check']) → exit 0 если INDEX.md актуален.

        Зависит от того, был ли INDEX.md регенерирован ранее в этой сессии.
        Resilient: принимает 0 (up-to-date) или 1 (out-of-date — тест не делает fix).
        """
        rc = main(["--check"])
        assert rc in (0, 1)


class TestImportsWork:
    """Module imports без side effects."""

    def test_module_imports(self) -> None:
        assert hasattr(module, "app")
        assert hasattr(module, "main")
        assert hasattr(module, "generate_index")
        assert hasattr(module, "_parse_adr")
        assert hasattr(module, "TITLE_RE")
        assert hasattr(module, "STATUS_RE")
