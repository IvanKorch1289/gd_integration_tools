"""P1-W1 (audit 2026-08-18): verify ContinueAsNewHandler is wired in workflow runtime.

Без fix — handler существовал, но production path не вызывал его.
С fix — DSL шаг ``- type: continue_as_new`` вызывает ``workflow.continue_as_new``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.backend.dsl.workflow.compiler.step_compilers import (
    compile_continue_as_new_step,
)
from src.backend.dsl.workflow.spec.advanced_declarations import ContinueAsNewDeclaration


@pytest.mark.unit
@pytest.mark.asyncio
async def test_continue_as_new_dispatch_registered() -> None:
    """P1-W1: ContinueAsNewDeclaration зарегистрирован в _STEP_DISPATCH."""
    from src.backend.dsl.workflow.compiler.step_compilers import (
        _STEP_DISPATCH,
        compile_continue_as_new_step,
    )

    assert ContinueAsNewDeclaration in _STEP_DISPATCH
    assert _STEP_DISPATCH[ContinueAsNewDeclaration] is compile_continue_as_new_step


@pytest.mark.unit
@pytest.mark.asyncio
async def test_continue_as_new_step_invokes_handler() -> None:
    """P1-W1: ``compile_continue_as_new_step`` вызывает ``handler.perform_continue``."""
    decl = ContinueAsNewDeclaration(
        same_workflow_id=True,
        same_input=True,
        search_attributes={"priority": "high"},
    )
    ctx = {"_input": {"foo": "bar"}, "_outputs": {}}

    mock_handler = MagicMock()
    with patch(
        "src.backend.dsl.workflow.handlers.continue_as_new_handler.ContinueAsNewHandler",
        return_value=mock_handler,
    ):
        result = await compile_continue_as_new_step(decl, ctx)

    mock_handler.perform_continue.assert_called_once()
    call_kwargs = mock_handler.perform_continue.call_args.kwargs
    assert call_kwargs["current_input"] == {"foo": "bar"}

    assert result["continued_as_new"] is True
    assert result["same_workflow_id"] is True
    assert result["same_input"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_continue_as_new_same_input_false_uses_none() -> None:
    """``same_input=False`` → current_input=None (handler использует body_snapshot)."""
    decl = ContinueAsNewDeclaration(same_workflow_id=True, same_input=False)
    ctx = {"_input": {"foo": "bar"}, "_outputs": {}}

    mock_handler = MagicMock()
    with patch(
        "src.backend.dsl.workflow.handlers.continue_as_new_handler.ContinueAsNewHandler",
        return_value=mock_handler,
    ):
        await compile_continue_as_new_step(decl, ctx)

    call_kwargs = mock_handler.perform_continue.call_args.kwargs
    assert call_kwargs["current_input"] is None


@pytest.mark.unit
def test_continue_as_new_declaration_yaml_parse() -> None:
    """YAML DSL ``- type: continue_as_new`` парсится в Pydantic."""
    decl = ContinueAsNewDeclaration.model_validate(
        {
            "type": "continue_as_new",
            "same_workflow_id": False,
            "same_input": True,
            "search_attributes": {"env": "prod"},
        },
    )
    assert decl.same_workflow_id is False
    assert decl.same_input is True
    assert decl.search_attributes == {"env": "prod"}


@pytest.mark.unit
def test_continue_as_new_declaration_defaults() -> None:
    """Defaults: same_workflow_id=True, same_input=True, search_attributes={}."""
    decl = ContinueAsNewDeclaration()
    assert decl.same_workflow_id is True
    assert decl.same_input is True
    assert decl.search_attributes == {}
