"""Unit-тесты SLA-оценки (Sprint 9 K3 W10).

.. note::
   ADR-0403 (волна 21): исполнитель SLA-трекинга (``SlaTracker``) и
   протокол диспетчера (``SlaAlertDispatcher``) удалены как мёртвый код —
   они не инстанцировались нигде в ``src/``, поэтому эскалация по SLA в
   рантайме не работала (owner-задача GAP-WF-4.5). Осталась чистая оценка
   SLA (``evaluate_sla``) — она же эмитит метрику
   ``workflow_sla_compliance_total``.
"""

from __future__ import annotations

import pytest

from src.backend.dsl.workflow.spec import SlaPolicy
from src.backend.services.workflows.sla_alerting import SlaBreachLevel, evaluate_sla


def test_evaluate_sla_none() -> None:
    record = evaluate_sla(
        workflow_id="wf-1",
        elapsed_seconds=10,
        soft_limit_seconds=60,
        hard_limit_seconds=300,
    )
    assert record.level is SlaBreachLevel.NONE


def test_evaluate_sla_soft() -> None:
    record = evaluate_sla(
        workflow_id="wf-1",
        elapsed_seconds=100,
        soft_limit_seconds=60,
        hard_limit_seconds=300,
    )
    assert record.level is SlaBreachLevel.SOFT


def test_evaluate_sla_hard() -> None:
    record = evaluate_sla(
        workflow_id="wf-1",
        elapsed_seconds=400,
        soft_limit_seconds=60,
        hard_limit_seconds=300,
    )
    assert record.level is SlaBreachLevel.HARD


def test_breach_record_to_dict_shape() -> None:
    record = evaluate_sla(
        workflow_id="wf-1",
        elapsed_seconds=10,
        soft_limit_seconds=60,
        hard_limit_seconds=300,
    )
    body = record.to_dict()
    assert body["workflow_id"] == "wf-1"
    assert body["level"] == "none"
    assert body["soft_limit_seconds"] == 60


def test_sla_policy_breach_action_validation() -> None:
    with pytest.raises(ValueError):
        SlaPolicy(
            soft_limit_seconds=10, hard_limit_seconds=20, breach_action="invalid_action"
        )
