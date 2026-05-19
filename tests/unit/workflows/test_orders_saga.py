"""Тесты :func:`build_orders_saga_workflow` (Sprint 4 К3-D §3).

Проверяют:
* Pydantic-валидацию декларации (имя, описание, тип шагов);
* Корректность forward/compensate цепочек (3 forward + 3 compensate);
* output_key на ключевых шагах (``order_id``, ``charge_id``);
* Smoke-compile через :func:`compile_workflow` — генерируется
  Temporal workflow-класс с ``@workflow.defn`` маркером.
"""
# ruff: noqa: S101

from __future__ import annotations

from src.backend.dsl.workflow.compiler import compile_workflow
from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    SagaDeclaration,
    WorkflowDeclaration,
)
from extensions.core_entities.orders.workflows.orders_saga import (
    build_orders_saga_workflow,
)


def test_orders_saga_declaration_is_valid_workflow() -> None:
    decl = build_orders_saga_workflow()
    assert isinstance(decl, WorkflowDeclaration)
    assert decl.name == "orders.create_with_payment"
    assert decl.description == "Создание заказа с резервом склада и оплатой"


def test_orders_saga_has_single_saga_step() -> None:
    decl = build_orders_saga_workflow()
    assert len(decl.steps) == 1
    assert isinstance(decl.steps[0], SagaDeclaration)


def test_orders_saga_forward_chain_has_three_steps() -> None:
    saga = build_orders_saga_workflow().steps[0]
    assert isinstance(saga, SagaDeclaration)
    forward_names = [step.name for step in saga.forward]
    assert forward_names == ["orders.create", "inventory.reserve", "payments.charge"]


def test_orders_saga_compensate_chain_has_three_steps() -> None:
    saga = build_orders_saga_workflow().steps[0]
    assert isinstance(saga, SagaDeclaration)
    compensate_names = [step.name for step in saga.compensate]
    assert compensate_names == [
        "orders.cancel",
        "inventory.release",
        "payments.refund",
    ]


def test_orders_saga_forward_compensate_length_match() -> None:
    """Симметричная saga: 3 forward + 3 compensate (1:1 откат)."""
    saga = build_orders_saga_workflow().steps[0]
    assert isinstance(saga, SagaDeclaration)
    assert len(saga.forward) == len(saga.compensate)


def test_orders_saga_output_keys_on_create_and_charge() -> None:
    """``orders.create`` → order_id, ``payments.charge`` → charge_id."""
    saga = build_orders_saga_workflow().steps[0]
    assert isinstance(saga, SagaDeclaration)
    forward_by_name = {step.name: step for step in saga.forward}
    assert forward_by_name["orders.create"].output_key == "order_id"
    assert forward_by_name["payments.charge"].output_key == "charge_id"
    # inventory.reserve без output_key (промежуточный side-effect).
    assert forward_by_name["inventory.reserve"].output_key is None


def test_orders_saga_steps_are_activity_declarations() -> None:
    """Все forward+compensate — ActivityDeclaration (no nested sagas)."""
    saga = build_orders_saga_workflow().steps[0]
    assert isinstance(saga, SagaDeclaration)
    for step in saga.forward + saga.compensate:
        assert isinstance(step, ActivityDeclaration)


def test_orders_saga_compiles_to_temporal_workflow_class() -> None:
    """Smoke: compile_workflow возвращает динамический @workflow.defn-класс."""
    decl = build_orders_saga_workflow()
    compiled = compile_workflow(decl)
    assert compiled.name == "orders.create_with_payment"
    # Класс реально получил @workflow.defn маркер.
    assert getattr(compiled.cls, "__temporal_workflow_definition", None) is not None
    # Имя класса — PascalCase из workflow_name.
    assert compiled.cls.__name__ == "OrdersCreateWithPaymentWorkflow"
