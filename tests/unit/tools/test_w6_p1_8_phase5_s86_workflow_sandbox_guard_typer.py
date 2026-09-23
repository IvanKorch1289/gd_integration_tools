"""Focused tests: W6 P1-8 Phase 5 — tools/s86_workflow_sandbox_guard.py argparse → typer+rich.

Validation:
1. Typer app help output.
2. main([--help]) backward-compat через CliRunner.
3. main() без args → exit 0 (по дефолту сканирует compiler path).
4. main(['--path', 'nonexistent']) → exit 2.
5. Module imports work.

Note: тесты используют importlib.util workaround для pytest --import-mode=importlib
(pre-existing pytest quirk, затрагивает все W6 P1-8 tests, см. ADR-0318/0319/0322/0323).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import typer
from typer.testing import CliRunner

# Workaround для pytest --import-mode=importlib.
_TOOLS_PATH = (
    Path(__file__).resolve().parents[3] / "tools" / "s86_workflow_sandbox_guard.py"
)
_spec = importlib.util.spec_from_file_location(
    "tools.s86_workflow_sandbox_guard", _TOOLS_PATH
)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)
app = module.app
main = module.main

runner = CliRunner()


class TestS86WorkflowSandboxGuardTyperMigration:
    """``tools/s86_workflow_sandbox_guard.py`` мигрирован на typer + rich."""

    def test_app_is_typer_instance(self) -> None:
        """app — typer.Typer, не argparse.ArgumentParser."""
        assert isinstance(app, typer.Typer)

    def test_no_argparse_import(self) -> None:
        """В s86_workflow_sandbox_guard.py НЕ должно быть import argparse."""
        source = open(_TOOLS_PATH).read()
        assert "import argparse" not in source
        assert "ArgumentParser" not in source

    def test_typer_help_formatted(self) -> None:
        """--help возвращает typer-formatted help."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "S86" in result.stdout or "Temporal" in result.stdout
        assert "--path" in result.stdout
        assert "--verbose" in result.stdout


class TestBackwardCompat:
    """main() callback поддерживает argv для backward-compat."""

    def test_main_help(self) -> None:
        """main(['--help']) → exit 0."""
        rc = main(["--help"])
        assert rc == 0

    def test_main_default_path(self) -> None:
        """main([]) → exit 0 (default path = compiler dir, no violations)."""
        rc = main([])
        assert rc == 0

    def test_main_nonexistent_path(self) -> None:
        """main(['--path', 'nonexistent_dir']) → exit 2 (path doesn't exist)."""
        rc = main(["--path", "/tmp/nonexistent_xyz_dir_for_test"])
        assert rc == 2

    def test_main_verbose(self) -> None:
        """main(['--verbose']) → exit 0 (default path, verbose output)."""
        rc = main(["--verbose"])
        assert rc == 0


class TestImportsWork:
    """Module imports без side effects."""

    def test_module_imports(self) -> None:
        assert hasattr(module, "app")
        assert hasattr(module, "main")
        assert hasattr(module, "scan_file")
        assert hasattr(module, "SAFE_PATTERNS")
        assert hasattr(module, "FORBIDDEN_PATTERNS")
        assert hasattr(module, "_console")
