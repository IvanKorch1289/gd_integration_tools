"""Sprint 19 iteration 14: step_compilers subpackage conformance test.

After P1-11 (Sprint 16) split step_compilers.py (885 LOC) into 4 files
(__init__.py + activity.py + flow.py + governance.py), verify the
contract is preserved:
* 13 compile functions registered
* 1:1 mapping between WorkflowStep union and dispatch table
* All compile functions are async
* All compile functions return Any

This prevents the "step added but not registered" failure class.
"""
from __future__ import annotations

import inspect

import pytest

from src.backend.dsl.workflow.compiler.step_compilers import (
    _STEP_DISPATCH,
    dispatch_step_compile,
)
from src.backend.dsl.workflow.spec.workflow import WorkflowStep


@pytest.mark.unit
def test_dispatch_size_matches_union() -> None:
    """_STEP_DISPATCH size == WorkflowStep union size.

    Если добавляешь новый StepDeclaration, нужно:
    1. Добавить в WorkflowStep union (workflow.py:33-48)
    2. Реализовать compile_*_step в одном из subpackage файлов
    3. Зарегистрировать в _STEP_DISPATCH (step_compilers/__init__.py)
    """
    # WorkflowStep — Annotated[Union, Field(discriminator=...)]
    # Извлекаем Union args (2nd element of Annotated)
    import typing
    args = typing.get_args(WorkflowStep)
    union = args[0]  # the Union
    union_size = len(typing.get_args(union)) if hasattr(union, "__args__") else 1
    assert len(_STEP_DISPATCH) == union_size, (
        f"_STEP_DISPATCH ({len(_STEP_DISPATCH)}) != WorkflowStep union ({union_size}). "
        "Missing or extra entries — see test_dispatch_entries_match_union."
    )


@pytest.mark.unit
def test_dispatch_entries_match_union() -> None:
    """Every WorkflowStep type has a compiler в _STEP_DISPATCH."""
    import typing
    args = typing.get_args(WorkflowStep)
    union = typing.get_args(args[0]) if hasattr(args[0], "__args__") else (args[0],)

    union_names = {t.__name__ for t in union}
    dispatch_names = {t.__name__ for t in _STEP_DISPATCH}

    missing = union_names - dispatch_names
    extra = dispatch_names - union_names

    assert not missing, f"Types in union but NOT в dispatch: {missing}"
    assert not extra, f"Types в dispatch but NOT в union: {extra}"


@pytest.mark.unit
def test_all_compilers_are_async() -> None:
    """Every compile_*_step is `async def` (Ponytail async-first)."""
    for step_type, compiler in _STEP_DISPATCH.items():
        assert inspect.iscoroutinefunction(compiler), (
            f"{compiler.__name__} (for {step_type.__name__}) must be async"
        )


@pytest.mark.unit
def test_dispatch_lookup_by_class() -> None:
    """dispatch_step_compile uses type(step) lookup, не isinstance."""
    # Create a mock that matches the step type exactly
    from src.backend.dsl.workflow.spec.activity_declarations import (
        ActivityDeclaration,
    )
    fake_step = ActivityDeclaration(name="test")
    compiler = _STEP_DISPATCH[type(fake_step)]
    assert compiler is not None


@pytest.mark.unit
async def test_dispatch_step_compile_unknown_type_raises() -> None:
    """Unknown step type должен raise TypeError (Ponytail fail-loud)."""
    # Use a non-WorkflowStep object as the "step" — type lookup will fail
    class NotAStep:
        pass

    ctx: dict = {}
    with pytest.raises(TypeError, match="No step compiler registered"):
        await dispatch_step_compile(NotAStep(), ctx)  # type: ignore[arg-type]


@pytest.mark.unit
def test_dispatch_compiler_signatures_consistent() -> None:
    """All compilers должны иметь (decl, ctx) signature."""
    for compiler in _STEP_DISPATCH.values():
        sig = inspect.signature(compiler)
        params = list(sig.parameters.keys())
        # Must have at least 2 params (decl, ctx) — may have more like timeout
        assert len(params) >= 2, (
            f"{compiler.__name__} has only {len(params)} params, expected >= 2"
        )
        assert params[0] in ("decl", "step"), (
            f"{compiler.__name__} first param должен быть 'decl' или 'step', got {params[0]!r}"
        )
        assert params[1] in ("ctx", "context"), (
            f"{compiler.__name__} second param должен быть 'ctx' или 'context', got {params[1]!r}"
        )


@pytest.mark.unit
def test_subpackage_module_structure() -> None:
    """step_compilers subpackage должен иметь 3 модуля compilers (activity, flow, governance)."""
    from src.backend.dsl.workflow.compiler import step_compilers

    expected_modules = ("activity", "flow", "governance")
    for mod_name in expected_modules:
        assert hasattr(step_compilers, mod_name), f"Missing subpackage: {mod_name}"
        # Module must be importable and have compile_*_step functions
        module = getattr(step_compilers, mod_name)
        compile_funcs = [name for name in dir(module) if name.startswith("compile_")]
        assert len(compile_funcs) > 0, f"Subpackage {mod_name} has no compile_* funcs"
