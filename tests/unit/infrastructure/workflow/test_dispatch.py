"""Unit tests for the step-kind dispatch dict in DSLStepExecutor.

Validates the Ponytail refactor (cycle 19 / S36-W17): if/elif chain
replaced with a dict lookup.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from src.backend.infrastructure.workflow.executor import (  # noqa: E402
    DSLStepExecutor,
    _STEP_KIND_DISPATCH,
)


def test_dispatch_has_7_kinds() -> None:
    """Sanity: all 7 declared kinds are registered."""
    assert len(_STEP_KIND_DISPATCH) == 7
    expected = {"sequential", "branch", "loop", "for_each", "sub_flow", "wait", "compensate"}
    assert set(_STEP_KIND_DISPATCH.keys()) == expected


def test_dispatch_handlers_callable() -> None:
    """Every handler is callable (lambda or function)."""
    for kind, handler in _STEP_KIND_DISPATCH.items():
        assert callable(handler), f"handler for {kind!r} is not callable"


def test_compensate_handler_noop() -> None:
    """compensate handler возвращает CONTINUE (no-op в normal flow)."""
    from src.backend.infrastructure.workflow.runner import StepOutcome

    class _ExecutorStub:
        pass

    result = _STEP_KIND_DISPATCH["compensate"](
        _ExecutorStub(), None, None, None
    )
    assert result.outcome == StepOutcome.CONTINUE
    assert result.events == []


def test_dispatch_consistency() -> None:
    """For every kind, method name _exec_<kind> exists on DSLStepExecutor (для не-compensate)."""
    expected_method_names = {
        "sequential": "_exec_sequential",
        "branch": "_exec_branch",
        "loop": "_exec_loop",
        "for_each": "_exec_for_each",
        "sub_flow": "_exec_sub_flow",
        "wait": "_exec_wait",
    }
    for kind, method_name in expected_method_names.items():
        assert hasattr(DSLStepExecutor, method_name), (
            f"DSLStepExecutor missing {method_name} for kind={kind!r}"
        )
