# ruff: noqa: S101
"""Тесты codemod ``tools/codemods/fix_except_clause.py``.

Покрывают трансформацию ``except A, B:`` → ``except (A, B):`` для нескольких
шаблонов: два имени, qualified-имя, три+ имени, идемпотентность, сохранение
trailing-комментариев. PLAN.md V22 §S17 DoD #2.
"""

from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

_TOOLS = Path(__file__).resolve().parents[3] / "tools"
sys.path.insert(0, str(_TOOLS))

from codemods.fix_except_clause import transform_source  # noqa: E402


class TestFixExceptClause:
    """Поведение codemod по разным синтаксическим формам ``except``."""

    def test_basic_two_names_wrapping(self) -> None:
        """``except A, B:`` → ``except (A, B):``."""
        source = dedent(
            """
            def f():
                try:
                    do()
                except ValueError, TypeError:
                    pass
            """
        ).lstrip()
        result = transform_source(source)
        assert "except (ValueError, TypeError):" in result
        assert "except ValueError, TypeError:" not in result

    def test_qualified_name(self) -> None:
        """Qualified-имя ``orjson.JSONDecodeError`` корректно оборачивается."""
        source = dedent(
            """
            def f():
                try:
                    do()
                except orjson.JSONDecodeError, TypeError:
                    pass
            """
        ).lstrip()
        result = transform_source(source)
        assert "except (orjson.JSONDecodeError, TypeError):" in result

    def test_three_or_more_names(self) -> None:
        """Случаи с 3 и 4 именами оборачиваются в один кортеж."""
        source = dedent(
            """
            def f():
                try:
                    do()
                except A, B, C:
                    pass
                try:
                    do2()
                except A, B, C, D:
                    pass
            """
        ).lstrip()
        result = transform_source(source)
        assert "except (A, B, C):" in result
        assert "except (A, B, C, D):" in result

    def test_idempotent_on_already_wrapped(self) -> None:
        """Повторный запуск на уже исправленных файлах не вносит изменений."""
        source = dedent(
            """
            def f():
                try:
                    do()
                except (ValueError, TypeError):
                    pass
            """
        ).lstrip()
        result = transform_source(source)
        assert result == source

    def test_preserves_trailing_comment(self) -> None:
        """Trailing-комментарий после ``:`` сохраняется без потерь."""
        source = dedent(
            """
            def f():
                try:
                    do()
                except ValueError, TypeError:  # noqa: PERF203
                    pass
            """
        ).lstrip()
        result = transform_source(source)
        assert "except (ValueError, TypeError):  # noqa: PERF203" in result
