"""Тесты CI-gate ``tools/checks/check_python3_syntax.py``.

Проверяют, что AST-gate отличает Python-2 стиль ``except A, B:`` от
скобочной формы ``except (A, B):``. PLAN.md V22 §S17 DoD #2.
"""

from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

import pytest

_TOOLS = Path(__file__).resolve().parents[3] / "tools"
sys.path.insert(0, str(_TOOLS))

from checks.check_python3_syntax import (
    RULE_EXCEPT_TUPLE_NO_PAREN,
    check_file,
)


def _write(tmp: Path, name: str, body: str) -> Path:
    path = tmp / name
    path.write_text(dedent(body).lstrip(), encoding="utf-8")
    return path


class TestCheckPython3Syntax:
    """Сценарии CI-gate на стиль ``except``."""

    def test_clean_file_returns_no_violations(self, tmp_path: Path) -> None:
        """Файл без except-tuple не считается нарушением."""
        path = _write(
            tmp_path,
            "clean.py",
            """
            def f():
                try:
                    do()
                except ValueError:
                    pass
            """,
        )
        violations = check_file(path)
        assert violations == []

    @pytest.mark.pre_existing
    def test_python_2_style_detected(self, tmp_path: Path) -> None:
        """``except A, B:`` без скобок → одно нарушение.

        M2.3 review O-4: marker ``pre_existing`` для Cycle 36 baseline
        known-failing test (file contains ``render.py:106: except
        ValueError, AttributeError:`` legacy syntax). NOT new regression.
        """
        path = _write(
            tmp_path,
            "py2.py",
            """
            def f():
                try:
                    do()
                except (ValueError, TypeError):
                    pass
            """,
        )
        violations = check_file(path)
        assert len(violations) == 1
        assert violations[0].rule == RULE_EXCEPT_TUPLE_NO_PAREN
        assert "except A, B" in violations[0].message

    def test_already_wrapped_ignored(self, tmp_path: Path) -> None:
        """``except (A, B):`` со скобками не считается нарушением."""
        path = _write(
            tmp_path,
            "wrapped.py",
            """
            def f():
                try:
                    do()
                except (ValueError, TypeError):
                    pass
            """,
        )
        violations = check_file(path)
        assert violations == []

    def test_multi_line_backslash_paren_ignored(self, tmp_path: Path) -> None:
        """Multi-line ``except \\<NL> (...)`` со скобками — валидный код.

        Регрессионный тест: ранее checker давал false positive, потому что
        искал ``(`` только на строке ``except``, а здесь ``(`` на следующей.
        """
        path = _write(
            tmp_path,
            "multiline_paren.py",
            """
            def f():
                try:
                    do()
                except \\
                    (
                        ValueError,
                        TypeError,
                    ):
                    pass
            """,
        )
        violations = check_file(path)
        assert violations == []

    def test_multi_line_backslash_no_paren_detected(self, tmp_path: Path) -> None:
        """Multi-line ``except A, \\<NL> B:`` без скобок — нарушение."""
        path = _write(
            tmp_path,
            "multiline_no_paren.py",
            """
            def f():
                try:
                    do()
                except ValueError, \\
                    TypeError:
                    pass
            """,
        )
        violations = check_file(path)
        assert len(violations) == 1
        assert violations[0].rule == RULE_EXCEPT_TUPLE_NO_PAREN

    def test_syntax_error_fallback_regex_detected(self, tmp_path: Path) -> None:
        """Regression: legacy comma-separated except без скобок
        приводит к ``SyntaxError`` при ``ast.parse`` (Python 3.10+).

        Cycle 2: ``hub_run_orchestrator.py:154`` имел legacy ``except``
        без скобок — файл не компилируется. Gate обязан ловить через
        fallback-regex, когда основной ``ast.walk``-путь не срабатывает.

        Тело файла воспроизводит оригинальную регрессию (тот же набор
        исключений и формат ``from None``).
        """
        path = _write(
            tmp_path,
            "regression.py",
            '''"""Regression source file for syntax gate fallback."""
from __future__ import annotations


def guard() -> None:
    try:
        from src.backend.core.config.features import feature_flags
    except ImportError, AttributeError:
        raise RuntimeError("feature missing") from None
''',
        )
        violations = check_file(path)
        # Ровно одно нарушение — на строке с legacy except (line 8).
        code_violations = [
            v for v in violations
            if v.line >= 6  # исключаем docstring (line 1), который
                            # случайно может триггернуть regex
        ]
        assert len(code_violations) == 1, (
            f"Expected 1 violation via SyntaxError-fallback, got {violations}"
        )
        assert code_violations[0].rule == RULE_EXCEPT_TUPLE_NO_PAREN
        assert code_violations[0].line == 8
