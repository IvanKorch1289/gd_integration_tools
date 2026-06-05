"""Тесты :func:`build_payments_saga_workflow` (Sprint 4 К3-D §3).

Проверяют:
* Pydantic-валидацию декларации (имя, описание, тип шагов);
* Корректность forward (3) / compensate (2) цепочек — asymmetric saga;
* output_key на authorize/capture (``auth_id``, ``charge_id``);
* Smoke-compile через :func:`compile_workflow`.
"""
# ruff: noqa: S101

from __future__ import annotations

import pytest

from extensions.credit_pipeline.workflows.payments_saga import (
    build_payments_saga_workflow,
)
from src.backend.dsl.workflow.compiler import compile_workflow
from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    SagaDeclaration,
    WorkflowDeclaration,
)


def test_payments_saga_declaration_is_valid_workflow() -> None:
    decl = build_payments_saga_workflow()
    assert isinstance(decl, WorkflowDeclaration)
    assert decl.name == "payments.charge_card"
    assert decl.description == "Зарядка карты с двух-фазной авторизацией"


def test_payments_saga_has_single_saga_step() -> None:
    decl = build_payments_saga_workflow()
    assert len(decl.steps) == 1
    assert isinstance(decl.steps[0], SagaDeclaration)


def test_payments_saga_forward_chain_has_three_steps() -> None:
    saga = build_payments_saga_workflow().steps[0]
    assert isinstance(saga, SagaDeclaration)
    forward_names = [step.name for step in saga.forward]
    assert forward_names == [
        "payments.validate_card",
        "payments.authorize",
        "payments.capture",
    ]


def test_payments_saga_compensate_chain_has_two_steps() -> None:
    """Asymmetric: validate_card не нуждается в откате."""
    saga = build_payments_saga_workflow().steps[0]
    assert isinstance(saga, SagaDeclaration)
    compensate_names = [step.name for step in saga.compensate]
    assert compensate_names == ["payments.void_authorization", "payments.void_capture"]


def test_payments_saga_forward_longer_than_compensate() -> None:
    """Asymmetric saga: 3 forward + 2 compensate.

    Compiler корректно обрабатывает: при failure validate_card (idx=0) —
    compensate skip (idx=0 за пределами compensate length=2 для
    положения completed[0]); при failure authorize (idx=1) — отрабатывает
    void_authorization; при failure capture (idx=2) — отрабатывает
    void_authorization + void_capture.
    """
    saga = build_payments_saga_workflow().steps[0]
    assert isinstance(saga, SagaDeclaration)
    assert len(saga.forward) > len(saga.compensate)


def test_payments_saga_output_keys_on_authorize_and_capture() -> None:
    saga = build_payments_saga_workflow().steps[0]
    assert isinstance(saga, SagaDeclaration)
    forward_by_name = {step.name: step for step in saga.forward}
    assert forward_by_name["payments.authorize"].output_key == "auth_id"
    assert forward_by_name["payments.capture"].output_key == "charge_id"
    # validate_card — pure check, output не сохраняется.
    assert forward_by_name["payments.validate_card"].output_key is None


def test_payments_saga_steps_are_activity_declarations() -> None:
    saga = build_payments_saga_workflow().steps[0]
    assert isinstance(saga, SagaDeclaration)
    for step in saga.forward + saga.compensate:
        assert isinstance(step, ActivityDeclaration)


def test_payments_saga_compiles_to_temporal_workflow_class() -> None:
    """Smoke: compile_workflow возвращает динамический @workflow.defn-класс."""
    pytest.importorskip("temporalio")
    decl = build_payments_saga_workflow()
    compiled = compile_workflow(decl)
    assert compiled.name == "payments.charge_card"
    assert getattr(compiled.cls, "__temporal_workflow_definition", None) is not None
    assert compiled.cls.__name__ == "PaymentsChargeCardWorkflow"
