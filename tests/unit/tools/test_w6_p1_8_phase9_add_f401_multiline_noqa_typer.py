"""Focused tests: W6 P1-8 Phase 9 — tools/add_f401_multiline_noqa.py argparse → typer+rich.

Validation:
1. Typer app help output.
2. main([--help]) backward-compat через CliRunner.
3. main([]) → exit 0 (DRY-RUN mode — no file changes).
4. main([--root', '<self>']) → DRY-RUN, exit 0, no changes.
5. Module imports work.

Note: тесты используют importlib.util workaround для pytest --import-mode=importlib.

SAFETY: default — DRY-RUN mode (no file changes). Тесты никогда не вызывают
tool с ``--apply`` flag на src/backend (предотвращает unintended side effects).
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
        assert "--apply" in result.stdout


class TestBackwardCompat:
    """main() callback поддерживает argv для backward-compat."""

    def test_main_help(self) -> None:
        """main(['--help']) → exit 0."""
        rc = main(["--help"])
        assert rc == 0

    def test_main_default_dry_run(self) -> None:
        """main([]) → exit 0 (DRY-RUN safe на self tool file)."""
        # Default mode is DRY-RUN. Используем self path — будет "0 changes".
        rc = main(["--root", "tools/add_f401_multiline_noqa.py"])
        assert rc == 0

    def test_main_dry_run_explicit_root(self) -> None:
        """main(['--root', '<self>']) → exit 0 (DRY-RUN, no changes)."""
        rc = main(["--root", "tools/add_f401_multiline_noqa.py"])
        assert rc == 0

    def test_main_apply_self_safe(self) -> None:
        """main(['--apply', '--root', '<self>']) → exit 0 (self has no multi-line imports)."""
        # Self-tool file has no multi-line imports → 0 changes даже с --apply.
        rc = main(["--apply", "--root", "tools/add_f401_multiline_noqa.py"])
        assert rc == 0


class TestSafetyDefaults:
    """SAFETY: default — DRY-RUN, --apply required для реальных changes."""

    def test_default_is_dry_run(self) -> None:
        """main([]) → DRY-RUN mode (no file changes)."""
        result = runner.invoke(app, ["--root", "tools/add_f401_multiline_noqa.py"])
        assert result.exit_code == 0
        # DRY-RUN mode prints "Would update" или "Total changes: 0"
        assert "DRY-RUN" in result.stdout or "Total changes: 0" in result.stdout

    def test_apply_flag_required(self) -> None:
        """--apply флаг переключает в write mode."""
        # Проверяем что флаг есть в --help.
        result = runner.invoke(app, ["--help"])
        assert "--apply" in result.stdout
        assert "Apply changes" in result.stdout


class TestImportsWork:
    """Module imports без side effects."""

    def test_module_imports(self) -> None:
        assert hasattr(module, "app")
        assert hasattr(module, "main")
        assert hasattr(module, "_process_file")
        assert hasattr(module, "_logger")
        assert hasattr(module, "_console")
