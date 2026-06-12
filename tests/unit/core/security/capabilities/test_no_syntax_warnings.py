"""S96 W2 — regression-блокировка против SyntaxWarning от invalid escape sequences.

Гарантирует что модули собираются БЕЗ ``SyntaxWarning: invalid escape sequence``.

S96 W2: ``tool_policy_integration.py:172`` имел ``\\`tools\\``` (legacy escape)
→ SyntaxWarning. Заменён на ````tools````.

Этот тест собирает ВСЕ модули core/security/capabilities/ и проверяет
что ``compileall`` не выдаёт SyntaxWarning.
"""
from __future__ import annotations

import py_compile
import warnings
from pathlib import Path

import pytest

CAPABILITIES_DIR = Path("src/backend/core/security/capabilities")


def _collect_python_files() -> list[Path]:
    """Собрать все .py в capabilities/."""
    return sorted(CAPABILITIES_DIR.rglob("*.py"))


def test_no_syntax_warnings_in_capabilities() -> None:
    """Никаких SyntaxWarning от invalid escape sequences."""
    py_files = _collect_python_files()
    assert py_files, f"No Python files in {CAPABILITIES_DIR}"

    caught: list[str] = []
    for path in py_files:
        with warnings.catch_warnings(record=True) as wlist:
            warnings.simplefilter("always", SyntaxWarning)
            try:
                # cfile=None → in-memory compile, не пишет .pyc файлы.
                # Собирает AST и байт-код; SyntaxWarning поднимается на compile step.
                py_compile.compile(  # noqa: S603
                    str(path), doraise=True, cfile=None
                )
            except py_compile.PyCompileError as exc:
                pytest.fail(f"Compile error in {path}: {exc}")
            syntax_warnings = [
                str(w.message)
                for w in wlist
                if issubclass(w.category, SyntaxWarning)
                and "invalid escape sequence" in str(w.message)
            ]
            caught.extend(f"{path.name}: {msg}" for msg in syntax_warnings)

    assert not caught, (
        f"Found {len(caught)} invalid escape sequence warnings:\n"
        + "\n".join(caught[:10])
    )


def test_tool_policy_integration_docstring_renders_clean() -> None:
    """``filter_tools_with_gate`` docstring не имеет legacy escapes."""
    import importlib

    mod = importlib.import_module(
        "src.backend.core.security.capabilities.tool_policy_integration"
    )
    docstring = mod.filter_tools_with_gate.__doc__ or ""
    # Legacy pattern: одиночный backslash + backtick
    assert r"\`" not in docstring, (
        f"Found legacy \\` escape in docstring:\n{docstring[:200]}"
    )
    # Правильный pattern: double-backtick reST literal
    assert "``tools``" in docstring, (
        "Expected reST literal ``tools`` in docstring"
    )
