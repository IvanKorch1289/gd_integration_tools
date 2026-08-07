"""B-1 fix (cycle 1): 4 workflow processors зарегистрированы через @processor().

D-A8-02 (P0): 4 процессора (WorkflowSubprocessProcessor,
WorkflowConvertProcessor, WorkflowClaimCheckProcessor,
WorkflowContinueAsNewProcessor) были объявлены как BaseProcessor с
required_capability, но не зарегистрированы в ProcessorRegistry.

Фикс: добавлены @processor() decorator'ы с capabilities + spec_schema +
meta во все 4 файла.
"""

# ruff: noqa: S101

from __future__ import annotations

from src.backend.dsl.engine.processors.workflow.best_practices import (
    claim_check,
    continue_as_new,
)
from src.backend.dsl.engine.processors.workflow import workflow_convert
from src.backend.dsl.engine.processors.workflow import workflow_subprocess
from src.backend.dsl.registry import get_processor_registry


class TestWorkflowProcessorsInRegistry:
    """B-1 fix (cycle 1): 4 процессора зарегистрированы через @processor()."""

    def test_workflow_subprocess_registered(self) -> None:
        """WorkflowSubprocessProcessor зарегистрирован с capabilities + spec_schema."""
        reg = get_processor_registry()
        fqn = "core:workflow_subprocess"
        assert fqn in reg, f"{fqn} должен быть зарегистрирован"
        spec = reg.get(fqn)
        assert "workflow.subprocess.invoke" in spec.capabilities
        assert spec.spec_schema is not None
        assert spec.spec_schema["type"] == "object"

    def test_workflow_convert_registered(self) -> None:
        """WorkflowConvertProcessor зарегистрирован с capabilities + spec_schema."""
        reg = get_processor_registry()
        fqn = "core:workflow_convert"
        assert fqn in reg
        spec = reg.get(fqn)
        assert "workflow.convert.format" in spec.capabilities
        assert spec.spec_schema is not None

    def test_workflow_claim_check_registered(self) -> None:
        """WorkflowClaimCheckProcessor зарегистрирован с capabilities + spec_schema."""
        reg = get_processor_registry()
        fqn = "core:workflow_claim_check"
        assert fqn in reg
        spec = reg.get(fqn)
        assert "workflow.claim_check.store" in spec.capabilities
        assert spec.spec_schema is not None

    def test_workflow_continue_as_new_registered(self) -> None:
        """WorkflowContinueAsNewProcessor зарегистрирован с capabilities + spec_schema."""
        reg = get_processor_registry()
        fqn = "core:workflow_continue_as_new"
        assert fqn in reg
        spec = reg.get(fqn)
        assert "workflow.continue_as_new.request" in spec.capabilities
        assert spec.spec_schema is not None

    def test_classes_importable(self) -> None:
        """Все 4 класса импортируются без ошибок (sanity-check)."""
        assert workflow_subprocess.WorkflowSubprocessProcessor is not None
        assert workflow_convert.WorkflowConvertProcessor is not None
        assert claim_check.WorkflowClaimCheckProcessor is not None
        assert continue_as_new.WorkflowContinueAsNewProcessor is not None
