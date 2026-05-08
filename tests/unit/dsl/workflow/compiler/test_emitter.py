"""Тесты :mod:`dsl.workflow.compiler.emitter`.

Проверяют:
* Корректность динамической генерации класса (имя, qualname, ``__doc__``).
* Сборку signal_names из :class:`SignalWaitDeclaration` шагов.
* Идемпотентность: двойной :func:`compile_workflow` даёт одинаковую
  структуру (replay-determinism).
* :func:`_safe_class_name` — edge cases для нестандартных имён.
* Применённый ``@workflow.defn`` обнаруживается через
  ``__temporal_workflow_definition``.
"""
# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.dsl.workflow.builder import WorkflowBuilder
from src.backend.dsl.workflow.compiler.emitter import (
    CompiledWorkflow,
    _safe_class_name,
    compile_workflow,
    compile_workflows,
)
from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    SignalWaitDeclaration,
    WorkflowDeclaration,
)


def _build_simple() -> WorkflowDeclaration:
    return WorkflowBuilder("orders.create").activity("orders.write").build()


def test_compile_returns_compiled_workflow() -> None:
    compiled = compile_workflow(_build_simple())
    assert isinstance(compiled, CompiledWorkflow)
    assert compiled.name == "orders.create"
    assert compiled.declaration.steps[0].name == "orders.write"


def test_compile_class_has_temporal_decorator() -> None:
    compiled = compile_workflow(_build_simple())
    # Temporal SDK маркирует defn через приватный атрибут.
    assert getattr(compiled.cls, "__temporal_workflow_definition", None) is not None


def test_compile_class_name_pascal_case() -> None:
    compiled = compile_workflow(_build_simple())
    # name="orders.create" → split('.') → ['orders', 'create'] → OrdersCreateWorkflow
    assert compiled.cls.__name__ == "OrdersCreateWorkflow"


def test_compile_class_doc_uses_description() -> None:
    decl = (
        WorkflowBuilder("ai.assess")
        .description("Оценка кредитной заявки")
        .activity("ai.score")
        .build()
    )
    compiled = compile_workflow(decl)
    assert compiled.cls.__doc__ == "Оценка кредитной заявки"


def test_compile_class_doc_fallback_when_no_description() -> None:
    compiled = compile_workflow(_build_simple())
    assert compiled.cls.__doc__ == "Workflow orders.create"


def test_signal_names_collected_from_signal_steps() -> None:
    decl = (
        WorkflowBuilder("hitl.flow")
        .activity("ai.retrieve")
        .wait_for_signal("manager_approve")
        .wait_for_signal("auditor_approve")
        .build()
    )
    compiled = compile_workflow(decl)
    assert set(compiled.signal_names) == {"manager_approve", "auditor_approve"}


def test_signal_names_deduplicated() -> None:
    decl = (
        WorkflowBuilder("hitl.dup")
        .wait_for_signal("approve")
        .activity("foo")
        .wait_for_signal("approve")  # duplicate by signal_name
        .build()
    )
    compiled = compile_workflow(decl)
    assert compiled.signal_names == ("approve",)


def test_signal_handler_attached_as_attribute() -> None:
    decl = (
        WorkflowBuilder("hitl.attr")
        .wait_for_signal("manager_approve")
        .build()
    )
    compiled = compile_workflow(decl)
    # _signal_attr_name заменяет '.' и '-' на '_' и префиксует _on_signal_.
    handler = getattr(compiled.cls, "_on_signal_manager_approve", None)
    assert handler is not None
    assert callable(handler)


def test_double_compile_produces_identical_structure() -> None:
    """Replay-determinism: повторная компиляция не меняет структуру."""
    decl = _build_simple()
    a = compile_workflow(decl)
    b = compile_workflow(decl)
    # Имена/signal_names стабильны.
    assert a.name == b.name
    assert a.signal_names == b.signal_names
    assert a.cls.__name__ == b.cls.__name__
    # Сами классы — разные объекты (новый type() при каждой компиляции).
    assert a.cls is not b.cls


def test_compile_workflows_bulk_preserves_order() -> None:
    declarations = [
        WorkflowBuilder("a.first").activity("foo").build(),
        WorkflowBuilder("b.second").activity("bar").build(),
        WorkflowBuilder("c.third").activity("baz").build(),
    ]
    compiled = compile_workflows(declarations)
    assert [c.name for c in compiled] == ["a.first", "b.second", "c.third"]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("orders.create", "OrdersCreateWorkflow"),
        ("simple", "SimpleWorkflow"),
        ("snake_case_name", "SnakeCaseNameWorkflow"),
        ("with.multiple.dots", "WithMultipleDotsWorkflow"),
    ],
)
def test_safe_class_name_pascal_conversion(raw: str, expected: str) -> None:
    assert _safe_class_name(raw) == expected


def test_safe_class_name_fallback_for_non_identifier() -> None:
    # name начинается с цифры — не валидный identifier после капитализации.
    assert _safe_class_name("123abc").startswith(("DynamicWorkflow", "1"))
    # Контракт: возвращаемое имя гарантированно identifier.
    candidate = _safe_class_name("123abc")
    assert candidate.isidentifier()


def test_compiled_workflow_init_creates_signals_dict() -> None:
    """__init__ init'ит ``_signals`` пустым словарём."""
    compiled = compile_workflow(_build_simple())
    instance = compiled.cls()
    assert hasattr(instance, "_signals")
    assert instance._signals == {}


def test_signal_handler_writes_to_signals_dict() -> None:
    """Signal handler сохраняет payload в self._signals."""
    import asyncio

    decl = WorkflowBuilder("hitl").wait_for_signal("ev").build()
    compiled = compile_workflow(decl)
    instance = compiled.cls()
    handler = getattr(compiled.cls, "_on_signal_ev")
    asyncio.run(handler(instance, {"k": "v"}))
    assert instance._signals == {"ev": {"k": "v"}}


def test_compile_preserves_declaration_reference() -> None:
    decl = _build_simple()
    compiled = compile_workflow(decl)
    # ``declaration`` сохранён по reference (frozen dataclass + immutable BaseModel).
    assert compiled.declaration is decl


def test_signal_attr_name_handles_dotted_signals() -> None:
    decl = (
        WorkflowBuilder("dot")
        .wait_for_signal("approve.manager")
        .wait_for_signal("approve-auditor")
        .build()
    )
    compiled = compile_workflow(decl)
    assert hasattr(compiled.cls, "_on_signal_approve_manager")
    assert hasattr(compiled.cls, "_on_signal_approve_auditor")


def test_compile_only_signal_step_workflow() -> None:
    """Workflow только из signal-wait (минимальный case)."""
    decl = WorkflowBuilder("only.signal").wait_for_signal("ev").build()
    compiled = compile_workflow(decl)
    assert compiled.signal_names == ("ev",)
    assert isinstance(compiled.declaration.steps[0], SignalWaitDeclaration)


def test_activity_step_propagated_to_declaration() -> None:
    decl = (
        WorkflowBuilder("test")
        .activity("foo.bar", timeout_s=10.0, output_key="result")
        .build()
    )
    compiled = compile_workflow(decl)
    step = compiled.declaration.steps[0]
    assert isinstance(step, ActivityDeclaration)
    assert step.timeout_s == 10.0
    assert step.output_key == "result"
