"""Unit-тесты ``services.workflow`` — coverage ratchet (Post-Plan A Sprint 4).

core/workflow service package facade (S45 W2 + Sprint 224 lazy proxy):
re-exports ``WorkflowDescriptor`` + ``workflow_registry`` через
``__getattr__``-based lazy proxy → infrastructure.workflow.registry.

Per Sprint 224 refactor: lazy proxy устраняет layer-violation
``services → infrastructure``. __getattr__ imports только при lookup.

Цель slice: 0% → 100% через __all__ audit + __getattr__ lazy resolution +
class/identity checks.
"""

from __future__ import annotations

import pytest

from src.backend.services import workflow


@pytest.mark.unit
class TestWorkflowFacadeAllExports:
    """``__all__`` audit + __getattr__ lazy resolution."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["WorkflowDescriptor", "workflow_registry"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(workflow, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in workflow.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 2 символа."""
        assert len(workflow.__all__) == 2

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает workflow registry facade (S45 W2)."""
        assert workflow.__doc__ is not None
        assert "Workflow" in workflow.__doc__


@pytest.mark.unit
class TestWorkflowFacadeIdentity:
    """Identity checks для lazy proxy."""

    def test_getattr_resolves_workflow_descriptor(self) -> None:
        """``workflow.WorkflowDescriptor`` → lazy resolves to actual class."""
        cls = workflow.WorkflowDescriptor
        assert isinstance(cls, type)

    def test_getattr_resolves_workflow_registry(self) -> None:
        """``workflow.workflow_registry`` → lazy resolves to instance."""
        registry = workflow.workflow_registry
        assert registry is not None
        # WorkflowRegistry has register/unregister methods
        assert hasattr(registry, "register")
        assert hasattr(registry, "unregister")

    def test_getattr_unknown_raises_attribute_error(self) -> None:
        """``workflow.UnknownSymbol`` → AttributeError (per Python convention)."""
        with pytest.raises(AttributeError, match="has no attribute"):
            _ = workflow.NonExistentSymbol  # type: ignore[attr-defined]

    def test_module_has_getattr(self) -> None:
        """``workflow.__getattr__`` — defined на module level (lazy proxy)."""
        assert hasattr(workflow, "__getattr__")
        assert callable(workflow.__getattr__)
