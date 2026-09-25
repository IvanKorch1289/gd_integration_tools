"""Regression test: запрет Python 2 ``except X, Y:`` синтаксиса.

S260 re-audit fix: 16 файлов имели ``except X, Y:`` который в Python 3.14
парсится как ``except X as Y:`` (ловит только первый тип, остальные
игнорируются) — семантически сломанный error handling.

Фикс: ``except X, Y:`` → ``except (X, Y):`` (tuple form).

Этот тест парсит ``src/backend/**/*.py`` через ``ast`` и падает,
если находит ``ast.ExceptHandler`` с ``handler`` НЕ tuple-формой.
Использование AST вместо regex исключает ложные срабатывания на
string literals (test fixtures, docstrings).

Note: S260 audit (cycle 152) показал, что detection через
``ast.ExceptHandler.name is not None`` молчит на Py3.10+ (PEG-парсер
обрабатывает ``except A, B:`` как кортеж без ``as``, ``name=None``).
Detection переписан на source-line analysis: ищем строки вида
``except X, Y:`` (запятая без скобок, без ``as``). Семантика ловли
типов на Py3.10+ идентична, но синтаксис архаичен и ломает Py3.9-.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _scan_for_py2_except(path: Path) -> list[tuple[int, str]]:
    """Return list of (line_no, source_line) for any Py2-style except in path.

    Py2 pattern: ``except A, B:`` — компилируется на Py3.10+ (PEG-парсер
    трактует как ``except (A, B):`` кортеж без ``as``), но семантически
    сломан/архаичен: ловит несколько типов как кортеж без явных скобок.
    Канонический Py3 синтаксис: ``except (A, B):`` — explicit tuple.

    Detection: line-source based (не AST-attribute ``name``, потому что на
    Py3.10+ ``except A, B:`` имеет ``name=None``, и AST-detection молчит).
    Эвристика:

    1. Строка начинается с ``except`` (после whitespace).
    2. Между ``except`` и ``:`` есть запятая.
    3. Скобки в этом сегменте несбалансированы (т.е. это не ``except (A, B):``).
    4. Нет ``as`` (т.е. не ``except A as B:`` — это валидный Py3 синтаксис).

    Миграция ``except A, B:`` → ``except (A, B):`` сохраняет Py3.10+ семантику
    (кортеж, name=None) и убирает Py2-архаизм + ломает совместимость с Py3.9-.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError, OSError:
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        # Fail-closed (аудит 2026-09-21): непарсящийся файл — сам по себе
        # нарушение, а не повод для молчаливого пропуска. Раньше этот
        # branch возвращал [] и скрывал 159-файловую регрессию.
        return [(e.lineno or 0, f"SYNTAX ERROR: {e.msg} — файл не парсится AST")]
    lines = text.splitlines()
    offenders: list[tuple[int, str]] = []
    # Walk ExceptHandler nodes — для каждого проверяем source-line
    # (Py3.10+ PEG делает ``except A, B:`` AST-эквивалентом ``except (A, B):``,
    # поэтому привязка только к AST-attribute ``name`` молчит на Py2-pattern).
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        line_no = getattr(node, "lineno", None)
        if not line_no or line_no > len(lines):
            continue
        line_text = lines[line_no - 1]
        # Strip comments
        code_part = line_text.split("#", 1)[0]
        stripped = code_part.lstrip()
        if not stripped.startswith("except"):
            continue
        # Найти двоеточие после ``except`` (исключая ``:=`` walrus).
        idx = len("except")
        colon_idx = None
        while idx < len(code_part):
            ch = code_part[idx]
            if ch == ":":
                if idx + 1 < len(code_part) and code_part[idx + 1] == "=":
                    idx += 2
                    continue
                colon_idx = idx
                break
            idx += 1
        if colon_idx is None:
            continue
        segment = code_part[code_part.index("except") + len("except") : colon_idx]
        if "," not in segment:
            continue
        if " as " in segment:
            continue  # это ``except A as B`` — валидный Py3 синтаксис
        open_p = segment.count("(")
        close_p = segment.count(")")
        if open_p == close_p and open_p > 0:
            continue  # это ``except (A, B):`` — валидный кортеж
        if open_p > close_p:
            continue  # неполный кортеж — другой gate
        offenders.append((line_no, line_text.strip()))
    return offenders


@pytest.mark.unit
def test_no_py2_except_syntax_in_src_backend() -> None:
    """Verify no ``except X, Y:`` (Python 2 syntax) remains in src/backend/.

    Python 3.14 silently parses this as ``except X as Y:`` (catches only first
    type), so we lint via AST (detects ``as`` binding with single-type handler).
    """
    src_backend = REPO_ROOT / "src" / "backend"
    if not src_backend.exists():
        pytest.skip("src/backend/ not present")
    offenders: list[tuple[Path, int, str]] = []
    for path in sorted(src_backend.rglob("*.py")):
        for line_no, line in _scan_for_py2_except(path):
            offenders.append((path, line_no, line))

    if offenders:
        msg_lines = [
            "Py2 except syntax (except X, Y:) found — semantically broken in Py3.14:"
        ]
        for path, line_no, line in offenders[:20]:
            rel = path.relative_to(REPO_ROOT)
            msg_lines.append(f"  {rel}:{line_no}: {line}")
        if len(offenders) > 20:
            msg_lines.append(f"  ... and {len(offenders) - 20} more")
        msg_lines.append(
            "\nFix: change `except X, Y:` to `except (X, Y):` (Python 3 tuple form)."
        )
        pytest.fail("\n".join(msg_lines))


@pytest.mark.unit
def test_no_py2_except_syntax_in_tests() -> None:
    """Same AST-based lint for tests/ — to prevent regression in test code."""
    tests_root = REPO_ROOT / "tests"
    if not tests_root.exists():
        pytest.skip("tests/ not present")
    offenders: list[tuple[Path, int, str]] = []
    for path in sorted(tests_root.rglob("*.py")):
        for line_no, line in _scan_for_py2_except(path):
            offenders.append((path, line_no, line))
    if offenders:
        msg_lines = ["Py2 except syntax in tests/ — same fix:"]
        for path, line_no, line in offenders[:20]:
            rel = path.relative_to(REPO_ROOT)
            msg_lines.append(f"  {rel}:{line_no}: {line}")
        pytest.fail("\n".join(msg_lines))
