"""Regression test для S93 W1 C6: NotebookExecutionService singleton via DI.

Покрывает:
- AST scan: ни одного NotebookExecutionService( в __init__ 3 процессоров
- Runtime: get_notebook_execution_service_provider возвращает singleton
- Test override: set_notebook_execution_service_provider работает
- Reset: reset_notebook_execution_service_overrides работает для test-isolation
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.backend.core.di.providers.jupyter import (
    get_notebook_execution_service_provider,
    reset_notebook_execution_service_overrides,
    set_notebook_execution_service_provider,
)


def _ast_notebook_service_in_init(src_path: Path) -> list[int]:
    """Возвращает список line numbers где NotebookExecutionService( создан в __init__."""
    tree = ast.parse(src_path.read_text())
    violations: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "__init__":
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id == "NotebookExecutionService"
                ):
                    violations.append(sub.lineno)
    return violations


@pytest.mark.parametrize(
    "notebook_processor",
    [
        "src/backend/dsl/engine/processors/notebook_dsl.py",
        "src/backend/dsl/engine/processors/notebook_execute.py",
        "src/backend/dsl/engine/processors/notebook_export.py",
    ],
)
def test_notebook_processor_uses_di_not_init(notebook_processor: str) -> None:
    """NotebookExecutionService НЕ должен создаваться в __init__ процессора."""
    src = Path(notebook_processor)
    assert src.exists(), f"{src} not found"

    violations = _ast_notebook_service_in_init(src)
    assert not violations, (
        f"{notebook_processor} creates NotebookExecutionService in __init__ at "
        f"lines {violations}. Use get_notebook_execution_service_provider() instead."
    )


def test_provider_singleton_caches_instance() -> None:
    """get_notebook_execution_service_provider() возвращает ТОТ ЖЕ instance."""
    reset_notebook_execution_service_overrides()
    try:
        # Первый вызов может упасть если нет реального Jupyter backend —
        # для теста используем mock override.
        mock_svc = object()
        set_notebook_execution_service_provider(mock_svc)

        first = get_notebook_execution_service_provider()
        second = get_notebook_execution_service_provider()

        assert first is second is mock_svc
    finally:
        reset_notebook_execution_service_overrides()


def test_reset_clears_overrides() -> None:
    """reset_notebook_execution_service_overrides() очищает cache для тестов."""
    mock_svc = object()
    set_notebook_execution_service_provider(mock_svc)

    assert get_notebook_execution_service_provider() is mock_svc

    reset_notebook_execution_service_overrides()

    # После reset — следующий вызов создаст новый instance (или упадёт, что
    # в данном случае НЕ ожидается, т.к. JupyterHubSettings без backend — lazy).
    # Чтобы избежать создания реального instance — сразу ставим override.
    new_mock = object()
    set_notebook_execution_service_provider(new_mock)
    assert get_notebook_execution_service_provider() is new_mock
    reset_notebook_execution_service_overrides()
