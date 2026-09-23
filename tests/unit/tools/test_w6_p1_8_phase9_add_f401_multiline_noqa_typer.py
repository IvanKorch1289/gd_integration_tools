"""Focused tests: W6 P1-8 Phase 9 — tools/add_f401_multiline_noqa.py argparse → typer+rich.

Validation:
1. Typer app help output.
2. main([--help]) backward-compat через CliRunner.
3. main([]) → exit 0.
4. Module imports work.

Note: тесты используют importlib.util workaround для pytest --import-mode=importlib.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import typer
from typer.testing import CliRunner

# Workaround для pytest --import-mode=importlib.
_TOOLS_PATH = (
    Path(__file__).resolve().parents[3] / "tools" / "add_f401_multiline_noqa.py"
)
_spec = importlib.util.spec_from_file_location(
    "tools.add_f401_multiline_noqa", _TOOLS_PATH
)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)
app = module.app
main = module.main

runner = CliRunner()


class TestAddF401MultilineNoqaTyperMigration:
    """``tools/add_f401_multiline_noqa.py`` мигрирован на typer + rich."""

    def test_app_is_typer_instance(self) -> None:
        """app — typer.Typer, не argparse.ArgumentParser."""
        assert isinstance(app, typer.Typer)

    def test_no_argparse_import(self) -> None:
        """В add_f401_multiline_noqa.py НЕ должно быть import argparse."""
        source = open(_TOOLS_PATH).read()
        assert "import argparse" not in source
        assert "ArgumentParser" not in source

    def test_typer_help_formatted(self) -> None:
        """--help возвращает typer-formatted help."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "F401" in result.stdout or "imports" in result.stdout
        assert "--root" in result.stdout
        assert "--verbose" in result.stdout


class TestBackwardCompat:
    """main() callback поддерживает argv для backward-compat."""

    def test_main_help(self) -> None:
        """main(['--help']) → exit 0."""
        rc = main(["--help"])
        assert rc == 0

    def test_main_default(self) -> None:
        """main([]) → exit 0 (dry-run safe на self)."""
        rc = main([])
        assert rc == 0

    def test_main_with_specific_root(self) -> None:
        """main(['--root', '<dir>']) → exit 0 или 1 (если есть изменения)."""
        rc = main(["--root", "tools/add_f401_multiline_noqa.py"])
        assert rc in (0, 1)


class TestImportsWork:
    """Module imports без side effects."""

    def test_module_imports(self) -> None:
        assert hasattr(module, "app")
        assert hasattr(module, "main")
        assert hasattr(module, "_process_file")
        assert hasattr(module, "_logger")
        assert hasattr(module, "_console")
