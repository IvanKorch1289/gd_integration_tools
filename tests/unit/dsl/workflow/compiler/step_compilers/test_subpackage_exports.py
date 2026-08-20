"""Sprint 19 iteration 17: step_compilers subpackage exports test.

After P1-11 (Sprint 16) split step_compilers.py into 4 files
(__init__.py + activity.py + flow.py + governance.py), verify that:
* Each subpackage exports the expected compile_* functions
* Functions are importable and callable
* The subpackage split didn't accidentally remove any function

This prevents regression where a subpackage file might lose a function
during future refactors.
"""
from __future__ import annotations

import pytest


EXPECTED_ACTIVITY_EXPORTS = [
    "compile_activity_step",
    "compile_signal_wait_step",
    "compile_sleep_step",
    "compile_pause_step",
    "compile_resume_step",
    "compile_sensor_step",
    "compile_agent_invoke_step",
]

EXPECTED_FLOW_EXPORTS = [
    "compile_saga_step",
    "compile_checkpoint_step",
    "compile_continue_as_new_step",
]

EXPECTED_GOVERNANCE_EXPORTS = [
    "compile_reflect_step",
    "compile_guardrail_step",
    "compile_escalate_step",
]


class TestSubpackageActivity:
    """activity.py exports — signal/control flow + activity execution."""

    @pytest.mark.parametrize("name", EXPECTED_ACTIVITY_EXPORTS)
    def test_activity_subpackage_exports_compile(self, name: str) -> None:
        from src.backend.dsl.workflow.compiler.step_compilers import activity

        assert hasattr(activity, name), f"activity missing: {name}"
        assert callable(getattr(activity, name))


class TestSubpackageFlow:
    """flow.py exports — saga/checkpoint/continue_as_new."""

    @pytest.mark.parametrize("name", EXPECTED_FLOW_EXPORTS)
    def test_flow_subpackage_exports_compile(self, name: str) -> None:
        from src.backend.dsl.workflow.compiler.step_compilers import flow

        assert hasattr(flow, name), f"flow missing: {name}"
        assert callable(getattr(flow, name))


class TestSubpackageGovernance:
    """governance.py exports — reflect/guardrail/escalate."""

    @pytest.mark.parametrize("name", EXPECTED_GOVERNANCE_EXPORTS)
    def test_governance_subpackage_exports_compile(self, name: str) -> None:
        from src.backend.dsl.workflow.compiler.step_compilers import governance

        assert hasattr(governance, name), f"governance missing: {name}"
        assert callable(getattr(governance, name))


@pytest.mark.unit
def test_subpackage_total_exports() -> None:
    """Total exports = 7 (activity) + 3 (flow) + 3 (governance) = 13 compile funcs."""
    expected_total = 13
    actual = (
        len(EXPECTED_ACTIVITY_EXPORTS)
        + len(EXPECTED_FLOW_EXPORTS)
        + len(EXPECTED_GOVERNANCE_EXPORTS)
    )
    assert actual == expected_total, (
        f"Subpackage export count mismatch: expected {expected_total}, got {actual}"
    )


@pytest.mark.unit
def test_no_duplicate_compile_functions_across_subpackages() -> None:
    """Each compile_* function должен быть только в одном subpackage.

    Если дублируется — Python "last wins" — actual behavior зависит от
    import order. Это regression risk.
    """
    from src.backend.dsl.workflow.compiler.step_compilers import (
        activity,
        flow,
        governance,
    )

    all_names = []
    for mod in (activity, flow, governance):
        for name in dir(mod):
            if name.startswith("compile_") and not name.startswith("_"):
                all_names.append((name, mod.__name__))

    # Group by name
    by_name: dict[str, list[str]] = {}
    for name, modname in all_names:
        by_name.setdefault(name, []).append(modname)

    duplicates = {n: mods for n, mods in by_name.items() if len(mods) > 1}
    assert not duplicates, (
        f"Compile functions duplicated across subpackages: {duplicates}"
    )


@pytest.mark.unit
def test_subpackage_init_registers_all_compile_functions() -> None:
    """__init__.py must register all 13 compile functions в _STEP_DISPATCH."""
    from src.backend.dsl.workflow.compiler.step_compilers import (
        _STEP_DISPATCH,
    )

    # Count compile functions from subpackages, EXCLUDING gateway helpers
    # (compile_and, compile_or, compile_xor) which are lazy-imported in
    # activity.py from `gateways.py` but never registered as workflow
    # step compilers (they're used inside compile_activity_step).
    from src.backend.dsl.workflow.compiler.step_compilers import (
        activity,
        flow,
        governance,
    )

    GATEWAY_HELPERS = {"compile_and", "compile_or", "compile_xor"}

    all_compile_funcs = set()
    for mod in (activity, flow, governance):
        for name in dir(mod):
            if name.startswith("compile_") and not name.startswith("_"):
                if name in GATEWAY_HELPERS:
                    continue  # gateway helpers, not workflow step compilers
                all_compile_funcs.add(name)

    # All should be in _STEP_DISPATCH
    dispatch_funcs = {compiler.__name__ for compiler in _STEP_DISPATCH.values()}
    missing = all_compile_funcs - dispatch_funcs
    assert not missing, f"Compile functions not in _STEP_DISPATCH: {missing}"
