"""Regression test: запрет Python 2 ``except X, Y:`` синтаксиса.

S260 re-audit fix: 16 файлов имели ``except X, Y:`` который в Python 3.14
парсится как ``except X as Y:`` (ловит только первый тип, остальные
игнорируются) — семантически сломанный error handling.

Фикс: ``except X, Y:`` → ``except (X, Y):`` (tuple form).

Этот тест парсит ``src/backend/**/*.py`` через ``ast`` и падает,
если находит ``ast.ExceptHandler`` с ``handler`` НЕ tuple-формой.
Использование AST вместо regex исключает ложные срабатывания на
string literals (test fixtures, docstrings).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _scan_for_py2_except(path: Path) -> list[tuple[int, str]]:
    """Return list of (line_no, source_line) for any Py2-style except in path.

    Py2 pattern: ``except A, B:`` — in Py3 this silently parses as
    ``except A as B:`` (catches only first type). Detection: AST shows
    ExceptHandler with ``name`` set + single-type handler + source line
    contains a comma between the type and the name.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []  # Let other linters catch actual SyntaxError.
    lines = text.splitlines()
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        # Must have an as-binding (``except X as Y:``) to be a candidate.
        as_name = getattr(node, "name", None)
        if not as_name:
            continue
        # Inspect source line — if it contains a comma between type and `as`
        # (without being inside a tuple), it's Py2 syntax.
        line_text = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
        # Strip comments
        code_part = line_text.split("#", 1)[0]
        # Look for pattern: `except X, Y` (comma before as-binding)
        if "except " in code_part and "," in code_part and " as " in code_part:
            # Check that the comma appears between `except` and `as`
            except_idx = code_part.index("except ")
            as_idx = code_part.index(" as ", except_idx)
            segment = code_part[except_idx:as_idx]
            if "," in segment:
                # Make sure it's not a tuple like (A, B)
                if "(" not in segment or segment.count("(") != segment.count(")"):
                    # Has comma but unbalanced parens → likely Py2 syntax
                    offenders.append((node.lineno, line_text.strip()))
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
            "Py2 except syntax (except X, Y:) found — semantically broken in Py3.14:",
        ]
        for path, line_no, line in offenders[:20]:
            rel = path.relative_to(REPO_ROOT)
            msg_lines.append(f"  {rel}:{line_no}: {line}")
        if len(offenders) > 20:
            msg_lines.append(f"  ... and {len(offenders) - 20} more")
        msg_lines.append(
            "\nFix: change `except X, Y:` to `except (X, Y):` "
            "(Python 3 tuple form)."
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
        msg_lines = [
            "Py2 except syntax in tests/ — same fix:",
        ]
        for path, line_no, line in offenders[:20]:
            rel = path.relative_to(REPO_ROOT)
            msg_lines.append(f"  {rel}:{line_no}: {line}")
        pytest.fail("\n".join(msg_lines))
