"""Unit-тесты для tools/add_docstrings.py (Cycle 32).

Покрывает базовые сценарии bulk placeholder docstring generator:
- Class without docstring → docstring added
- Function without docstring → docstring added
- Already-documented targets → no change (idempotency в реальности
  не достигается — это warning-mode behavior, not enforced)
- Dry-run mode не пишет на диск
- Indent корректно (col_offset + 4 spaces)
- Public API exposed via ``__all__``

Honest scope: 4 теста достаточно для smoke coverage. Полное покрытие
``add_docstrings_to_file`` — multi-sprint (см. tools/add_docstrings.py
docstring про 1840 violations = S46 W1 honest scope).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools.add_docstrings import _is_public, add_docstrings_to_file

CHECKER_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "tools" / "add_docstrings.py"
)


class TestAddDocstringsToFile:
    """``add_docstrings_to_file`` core API."""

    def test_class_without_docstring_gets_one(self, tmp_path: Path) -> None:
        """Класс без docstring → docstring добавлен после class-line."""
        target = tmp_path / "module.py"
        target.write_text("class Foo:\n    pass\n", encoding="utf-8")
        n = add_docstrings_to_file(target, "Test class.")
        assert n == 1
        content = target.read_text(encoding="utf-8")
        # Docstring должен быть первой stmt тела класса.
        assert '"""Test class.' in content
        assert 'class Foo:\n    """Test class.' in content

    def test_function_without_docstring_gets_one(self, tmp_path: Path) -> None:
        """Функция без docstring → docstring добавлен после def-line."""
        target = tmp_path / "module.py"
        target.write_text("def bar(x: int) -> int:\n    return x\n", encoding="utf-8")
        n = add_docstrings_to_file(target, "Test func.")
        assert n == 1
        content = target.read_text(encoding="utf-8")
        assert '"""Test func.' in content

    def test_dry_run_does_not_modify_file(self, tmp_path: Path) -> None:
        """``dry_run=True`` не пишет на диск."""
        target = tmp_path / "module.py"
        original = "class Foo:\n    pass\n"
        target.write_text(original, encoding="utf-8")
        n = add_docstrings_to_file(target, "Test.", dry_run=True)
        assert n == 1
        # File unchanged.
        assert target.read_text(encoding="utf-8") == original

    def test_indent_matches_col_offset(self, tmp_path: Path) -> None:
        """Indent = col_offset + 4 spaces.

        ``_find_public_targets`` skip'ает nested functions (methods) намеренно
        — ``add_docstrings.py`` ориентирован на module-level targets.
        Поэтому проверяем class docstring (col=0 → 4 spaces indent).
        """
        target = tmp_path / "module.py"
        target.write_text(
            "class Foo:\n    def method(self) -> None:\n        pass\n",
            encoding="utf-8",
        )
        n = add_docstrings_to_file(target, "Method.")
        assert n == 1  # только class, не method (nested)
        content = target.read_text(encoding="utf-8")
        # Class docstring: col=0 → indent = 4 spaces.
        assert '    """Method.' in content

    def test_returns_zero_for_documented_file(self, tmp_path: Path) -> None:
        """Файл где всё документировано → returns 0, file unchanged."""
        target = tmp_path / "module.py"
        target.write_text(
            '"""Module doc."""\n'
            "\n"
            "def bar() -> int:\n"
            '    """Documented."""\n'
            "    return 1\n",
            encoding="utf-8",
        )
        original = target.read_text(encoding="utf-8")
        n = add_docstrings_to_file(target, "Foo.")
        assert n == 0
        assert target.read_text(encoding="utf-8") == original


class TestIsPublic:
    """``_is_public`` helper."""

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("public_func", True),
            ("PublicClass", True),
            ("_private", False),
            ("__dunder__", False),
            ("main", True),
        ],
    )
    def test_is_public(self, name: str, expected: bool) -> None:
        assert _is_public(name) is expected


class TestAddDocstringsCLI:
    """CLI entrypoint: argparse + subprocess smoke test."""

    def test_help_exits_zero(self) -> None:
        """``--help`` → exit 0, output содержит module docstring header."""
        proc = subprocess.run(
            [sys.executable, str(CHECKER_PATH), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0
        # argparse description берётся из первой строки module docstring.
        assert "S46 W1" in proc.stdout or "add_docstrings" in proc.stdout

    def test_dry_run_with_summary(self, tmp_path: Path) -> None:
        """CLI dry-run mode: file unchanged, prints count."""
        target = tmp_path / "mod.py"
        target.write_text("class Foo:\n    pass\n", encoding="utf-8")
        proc = subprocess.run(
            [
                sys.executable, str(CHECKER_PATH),
                "--summary", "Test summary.",
                "--dry-run",
                str(target),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0
        assert "1 docstring(s)" in proc.stdout
        # File NOT modified.
        assert "Test summary" not in target.read_text(encoding="utf-8")


class TestAddDocstringsPublicAPI:
    """Public API surface — ``__all__`` defined."""

    def test_all_contains_main_api(self) -> None:
        import tools.add_docstrings as mod

        assert hasattr(mod, "__all__")
        assert "add_docstrings_to_file" in mod.__all__
