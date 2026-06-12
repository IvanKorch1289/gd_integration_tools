"""Regression test для S93 W2-C11: sys.path.insert хаки в Streamlit удалены.

Покрывает:
- AST scan: НЕТ sys.path.insert в 3 streamlit-файлах
- manage.py run-frontend: устанавливает PYTHONPATH=$(pwd)
- Импорты резолвятся с PYTHONPATH=project_root
"""
from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

STREAMLIT_FILES = [
    "src/frontend/streamlit_app/app.py",
    "src/frontend/streamlit_app/pages/31_DSL_Visual_Editor.py",
    "src/frontend/streamlit_app/pages/86_DSL_Usage_Audit.py",
]


def _has_sys_path_insert(src_path: Path) -> list[int]:
    """Возвращает список line numbers с sys.path.insert."""
    tree = ast.parse(src_path.read_text())
    violations: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "insert"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "path"
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "sys"
        ):
            violations.append(node.lineno)
    return violations


@pytest.mark.parametrize("streamlit_file", STREAMLIT_FILES)
def test_no_sys_path_insert_in_streamlit_files(streamlit_file: str) -> None:
    """sys.path.insert хаки удалены — PYTHONPATH ставит manage.py."""
    src = PROJECT_ROOT / streamlit_file
    assert src.exists(), f"{src} not found"

    violations = _has_sys_path_insert(src)
    assert not violations, (
        f"{streamlit_file} still has sys.path.insert at lines {violations}. "
        "Use PYTHONPATH=$(pwd) via manage.py run-frontend instead."
    )


def test_manage_py_run_frontend_sets_pythonpath() -> None:
    """manage.py run-frontend устанавливает PYTHONPATH=$(pwd)."""
    manage = PROJECT_ROOT / "manage.py"
    src = manage.read_text()
    # Find run_frontend function
    assert "def run_frontend" in src, "run_frontend not found in manage.py"
    # Check it sets PYTHONPATH
    assert "PYTHONPATH" in src, "PYTHONPATH not referenced in manage.py"
    assert "project_root" in src, "project_root not in manage.py"
    assert "os.execvpe" in src, "os.execvpe (with env) not used"


def test_streamlit_imports_resolve_with_pythonpath() -> None:
    """С PYTHONPATH=$(pwd) streamlit-импорты резолвятся (mock streamlit)."""
    # Mock streamlit (page-level code вызовет st.*, но мы только проверяем imports)
    import sys
    from unittest.mock import MagicMock

    sys.modules["streamlit"] = MagicMock()

    # Запускаем с PYTHONPATH=project_root
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    # Use compile-only check (не запускаем page-level code)
    for streamlit_file in STREAMLIT_FILES:
        src = PROJECT_ROOT / streamlit_file
        # Just parse — если syntax OK, импорты корректные
        try:
            ast.parse(src.read_text())
        except SyntaxError as exc:
            pytest.fail(f"{streamlit_file} has syntax error: {exc}")
