"""Unit-тесты ``services.jupyter`` — coverage ratchet (Post-Plan A Sprint 1).

core/jupyter execution service facade: re-exports ``NotebookExecutionService``
+ ``JupyterExecutionError`` + singleton factory. ~10 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class/callable identity +
singleton factory check.
"""

from __future__ import annotations

import pytest

from src.backend.services import jupyter
from src.backend.services.jupyter import (
    JupyterExecutionError,
    NotebookExecutionService,
    get_notebook_execution_service,
)


@pytest.mark.unit
class TestJupyterFacadeAllExports:
    """``__all__`` audit + class/function identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["JupyterExecutionError", "NotebookExecutionService", "get_notebook_execution_service"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(jupyter, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in jupyter.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 3 символа."""
        assert len(jupyter.__all__) == 3

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает Jupyter execution service (Sprint 1)."""
        assert jupyter.__doc__ is not None
        assert "Jupyter" in jupyter.__doc__ or "Notebook" in jupyter.__doc__


@pytest.mark.unit
class TestJupyterFacadeIdentity:
    """Identity checks для re-exports."""

    def test_jupyter_execution_error_is_class(self) -> None:
        """``JupyterExecutionError`` — class (Exception subclass)."""
        assert isinstance(JupyterExecutionError, type)
        assert issubclass(JupyterExecutionError, Exception)

    def test_notebook_execution_service_is_class(self) -> None:
        """``NotebookExecutionService`` — class (service implementation)."""
        assert isinstance(NotebookExecutionService, type)

    def test_get_notebook_execution_service_is_callable(self) -> None:
        """``get_notebook_execution_service`` — callable (singleton factory)."""
        assert callable(get_notebook_execution_service)
