"""Тесты YAML round-trip API для WorkflowDeclaration (Sprint 4 K3 W2).

Покрывает:
* Round-trip ``builder → to_yaml → from_yaml → declaration`` для эталонных
  workflow (orders_saga, payments_saga).
* :func:`diff` для added/removed/modified-step сценариев и version-changed.
* Feature-gate ``workflow_yaml_round_trip``: при выключенном flag-е
  :func:`from_yaml` бросает :class:`FeatureDisabledError`.
* Поведение ``version`` поля: default ``"1.0"`` и semver-валидация.
* Отказ при неизвестном типе шага (Pydantic ValidationError).
"""
# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from extensions.core_entities.orders.workflows.orders_saga import (
    build_orders_saga_workflow,
)
from extensions.credit_pipeline.workflows.payments_saga import (
    build_payments_saga_workflow,
)
from src.backend.dsl.workflow import (
    FeatureDisabledError,
    WorkflowBuilder,
    WorkflowDeclaration,
    WorkflowDiff,
    diff,
    from_yaml,
    to_yaml,
)


def _enable_round_trip() -> "patch[bool]":
    """Контекст-менеджер для активации feature_flags.workflow_yaml_round_trip."""
    return patch(
        "src.backend.core.config.features.feature_flags.workflow_yaml_round_trip", True
    )


# ── Round-trip для эталонных workflow ──


def test_yaml_roundtrip_orders_saga() -> None:
    """``build_orders_saga_workflow()`` сохраняется и восстанавливается из YAML."""
    decl = build_orders_saga_workflow()
    yaml_text = to_yaml(decl)
    assert "orders.create_with_payment" in yaml_text
    assert "saga" in yaml_text

    with _enable_round_trip():
        restored = from_yaml(yaml_text)

    assert restored == decl
    assert restored.name == "orders.create_with_payment"
    assert restored.version == "1.0"


def test_yaml_roundtrip_payments_saga() -> None:
    """``build_payments_saga_workflow()`` сохраняется и восстанавливается из YAML."""
    decl = build_payments_saga_workflow()
    yaml_text = to_yaml(decl)
    assert "payments.charge_card" in yaml_text

    with _enable_round_trip():
        restored = from_yaml(yaml_text)

    assert restored == decl
    assert restored.name == "payments.charge_card"


# ── diff: added/removed/modified/version ──


def test_diff_added_steps() -> None:
    """``diff()`` корректно фиксирует добавленные шаги в decl_b."""
    a = WorkflowBuilder("flow").activity("step.one").build()
    b = (
        WorkflowBuilder("flow")
        .activity("step.one")
        .activity("step.two")
        .activity("step.three")
        .build()
    )
    result = diff(a, b)
    assert isinstance(result, WorkflowDiff)
    assert "activity:step.two" in result.added_steps
    assert "activity:step.three" in result.added_steps
    assert result.removed_steps == ()
    assert result.modified_steps == ()
    assert result.version_changed is None


def test_diff_removed_steps() -> None:
    """``diff()`` корректно фиксирует удалённые шаги из decl_a."""
    a = WorkflowBuilder("flow").activity("step.one").activity("step.two").build()
    b = WorkflowBuilder("flow").activity("step.one").build()
    result = diff(a, b)
    assert result.removed_steps == ("activity:step.two",)
    assert result.added_steps == ()


def test_diff_modified_steps() -> None:
    """``diff()`` фиксирует шаг с одинаковым identity, но разным содержимым."""
    a = WorkflowBuilder("flow").activity("step.one", timeout_s=10.0).build()
    b = WorkflowBuilder("flow").activity("step.one", timeout_s=30.0).build()
    result = diff(a, b)
    assert result.modified_steps == ("activity:step.one",)
    assert result.added_steps == ()
    assert result.removed_steps == ()


def test_diff_version_changed() -> None:
    """``diff()`` фиксирует изменение ``version`` через tuple (old, new)."""
    a = WorkflowDeclaration.model_validate(
        {
            "name": "flow",
            "version": "1.0",
            "steps": [{"type": "activity", "name": "step.one"}],
        }
    )
    b = WorkflowDeclaration.model_validate(
        {
            "name": "flow",
            "version": "2.0",
            "steps": [{"type": "activity", "name": "step.one"}],
        }
    )
    result = diff(a, b)
    assert result.version_changed == ("1.0", "2.0")


# ── from_yaml: безопасность и feature-gate ──


def test_from_yaml_unknown_step_raises() -> None:
    """Неизвестный ``type`` шага → :class:`pydantic.ValidationError`."""
    yaml_text = """
name: bad.flow
version: "1.0"
steps:
  - type: unknown_step_type
    name: foo
"""
    with _enable_round_trip(), pytest.raises(ValidationError):
        from_yaml(yaml_text)


def test_version_field_default() -> None:
    """Поле ``version`` имеет default ``"1.0"`` и принимает semver."""
    wf = WorkflowBuilder("flow").activity("step.one").build()
    assert wf.version == "1.0"

    # Принимает MAJOR.MINOR.PATCH
    wf_patch = WorkflowDeclaration.model_validate(
        {
            "name": "flow",
            "version": "2.5.7",
            "steps": [{"type": "activity", "name": "x"}],
        }
    )
    assert wf_patch.version == "2.5.7"

    # Отклоняет невалидные строки
    with pytest.raises(ValidationError):
        WorkflowDeclaration.model_validate(
            {
                "name": "flow",
                "version": "v1.0",
                "steps": [{"type": "activity", "name": "x"}],
            }
        )


def test_from_yaml_disabled_when_feature_off() -> None:
    """При выключенном ``workflow_yaml_round_trip`` :func:`from_yaml` бросает FeatureDisabledError."""
    decl = WorkflowBuilder("flow").activity("step.one").build()
    yaml_text = to_yaml(decl)

    # Явно патчим в False (default-OFF подтверждаем явно)
    with (
        patch(
            "src.backend.core.config.features.feature_flags.workflow_yaml_round_trip",
            False,
        ),
        pytest.raises(FeatureDisabledError, match="workflow_yaml_round_trip"),
    ):
        from_yaml(yaml_text)
