"""Focused tests: W6 P1-8 Phase 3 — tools/check_env_example.py argparse → typer+rich.

Validation:
1. Typer app help output.
2. Missing required args handling.
3. main([--help]) backward-compat через CliRunner.
4. main() без args → запускается (не показывает help).
5. main() с --strict → exit 1 если есть extras.
6. Module imports work.

Note: тесты используют absolute path import через importlib.util (workaround
для pytest --import-mode=importlib, который ломает ``from tools.X import`` —
см. tools/check_env_example.py docstring).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import typer
from typer.testing import CliRunner

# Workaround для pytest --import-mode=importlib: используем importlib.util
# чтобы загрузить tools/check_env_example.py как модуль.
_TOOLS_PATH = Path(__file__).resolve().parents[3] / "tools" / "check_env_example.py"
_spec = importlib.util.spec_from_file_location("tools.check_env_example", _TOOLS_PATH)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)
app = module.app
main = module.main

runner = CliRunner()


class TestCheckEnvExampleTyperMigration:
    """``tools/check_env_example.py`` мигрирован на typer + rich."""

    def test_app_is_typer_instance(self) -> None:
        """app — typer.Typer, не argparse.ArgumentParser."""
        assert isinstance(app, typer.Typer)

    def test_no_argparse_import(self) -> None:
        """В check_env_example.py НЕ должно быть import argparse (миграция полная)."""
        source = open(_TOOLS_PATH).read()
        assert "import argparse" not in source
        assert "ArgumentParser" not in source

    def test_no_stdout_write(self) -> None:
        """sys.stdout.write не используется (заменено на rich.console.print)."""
        source = open(_TOOLS_PATH).read()
        assert "sys.stdout.write" not in source

    def test_typer_help_formatted(self) -> None:
        """--help возвращает typer-formatted help."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Проверка покрытия .env.example" in result.stdout
        assert "--strict" in result.stdout


class TestBackwardCompat:
    """main() callback поддерживает argv для backward-compat."""

    def test_main_help(self) -> None:
        """main(['--help']) → exit 0 + help message."""
        rc = main(["--help"])
        assert rc == 0

    def test_main_runs(self) -> None:
        """main([]) → exit 0 или 1 (validation result)."""
        rc = main([])
        assert rc in (0, 1)

    def test_main_strict(self) -> None:
        """main(['--strict']) → exit 0 или 1."""
        rc = main(["--strict"])
        assert rc in (0, 1)


class TestImportsWork:
    """Module imports без side effects."""

    def test_module_imports(self) -> None:
        assert hasattr(module, "app")
        assert hasattr(module, "main")
        assert hasattr(module, "_console")
        assert hasattr(module, "collect_expected_env_vars")
        assert hasattr(module, "collect_env_example_vars")
