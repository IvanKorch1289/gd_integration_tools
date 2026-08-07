"""D-AUDIT-A8-06 fix (cycle 1): WorkflowBuilder.then() method.

D-A8-06 (P0): extensions/core_entities/orders/workflows/orders_dsl.py
использует .then(ActivityDeclaration(...)) в 6 местах, но WorkflowBuilder
не имел этого метода — production extension был broken.

Фикс: добавлен fluent ``then(step: WorkflowStep) -> Self`` метод в
src/backend/dsl/workflow/builder/__init__.py.
"""

# ruff: noqa: S101

from __future__ import annotations

from src.backend.dsl.workflow.builder import WorkflowBuilder
from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    PauseDeclaration,
    ResumeDeclaration,
    SleepDeclaration,
)


class TestWorkflowBuilderThen:
    """D-AUDIT-A8-06 fix (cycle 1): WorkflowBuilder.then() fluent method."""

    def test_then_method_exists(self) -> None:
        """WorkflowBuilder имеет метод then."""
        assert hasattr(WorkflowBuilder, "then"), (
            "WorkflowBuilder должен иметь .then() метод (D-AUDIT-A8-06 fix)"
        )

    def test_then_appends_activity_declaration(self) -> None:
        """then(ActivityDeclaration) appends to _steps."""
        b = WorkflowBuilder("test")
        b.then(ActivityDeclaration(name="step1", args={"key": "value"}))

        assert len(b._steps) == 1
        assert isinstance(b._steps[0], ActivityDeclaration)
        assert b._steps[0].name == "step1"

    def test_then_appends_sleep_declaration(self) -> None:
        """then(SleepDeclaration) appends to _steps."""
        b = WorkflowBuilder("test")
        b.then(SleepDeclaration(duration_s=2.5))

        assert len(b._steps) == 1
        assert isinstance(b._steps[0], SleepDeclaration)
        assert b._steps[0].duration_s == 2.5

    def test_then_chaining_returns_self(self) -> None:
        """then() возвращает self для fluent chaining."""
        b = WorkflowBuilder("test")
        result = b.then(ActivityDeclaration(name="a", args={}))

        assert result is b, "then() должен возвращать self"

    def test_then_chain_multiple_steps(self) -> None:
        """Цепочка .then().then().then() работает корректно."""
        b = WorkflowBuilder("test")
        b.then(ActivityDeclaration(name="a", args={}))
        b.then(SleepDeclaration(duration_s=1.0))
        b.then(PauseDeclaration())
        b.then(ResumeDeclaration())

        assert len(b._steps) == 4
        step_types = [type(s).__name__ for s in b._steps]
        assert step_types == [
            "ActivityDeclaration",
            "SleepDeclaration",
            "PauseDeclaration",
            "ResumeDeclaration",
        ]

    def test_then_combined_with_fluent_methods(self) -> None:
        """then() работает совместно с другими fluent методами (.activity, .sleep)."""
        b = WorkflowBuilder("test")
        b.activity("act1")
        b.then(SleepDeclaration(duration_s=5.0))
        b.sleep(duration_s=3.0)

        assert len(b._steps) == 3
