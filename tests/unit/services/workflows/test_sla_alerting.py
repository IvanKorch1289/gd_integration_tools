"""Unit-тесты SLA alerting (Sprint 9 K3 W10)."""

from __future__ import annotations

import asyncio

import pytest

from src.backend.dsl.workflow.spec import SlaPolicy
from src.backend.services.workflows.sla_alerting import (
    InMemorySlaAlertDispatcher,
    SlaBreachLevel,
    SlaTracker,
    evaluate_sla,
)


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


@pytest.mark.asyncio
async def test_tracker_emits_soft_breach() -> None:
    dispatcher = InMemorySlaAlertDispatcher()
    tracker = SlaTracker(dispatcher=dispatcher)
    sla = SlaPolicy(
        soft_limit_seconds=0.05,
        hard_limit_seconds=10.0,
        escalation_email="ops@bank.local",
    )
    await tracker.track(workflow_id="wf-fast", sla=sla)
    await asyncio.sleep(0.1)
    breaches = await tracker._check_once()
    assert len(breaches) == 1
    assert breaches[0].level is SlaBreachLevel.SOFT
    assert dispatcher.sent[0]["email"] == "ops@bank.local"


@pytest.mark.asyncio
async def test_tracker_emits_hard_breach_and_callback() -> None:
    dispatcher = InMemorySlaAlertDispatcher()
    cancelled: list[str] = []

    async def on_hard(workflow_id: str) -> None:
        cancelled.append(workflow_id)

    tracker = SlaTracker(dispatcher=dispatcher, on_hard_breach=on_hard)
    sla = SlaPolicy(
        soft_limit_seconds=0.01,
        hard_limit_seconds=0.05,
        breach_action="cancel",
        escalation_slack="#wf-alerts",
    )
    await tracker.track(workflow_id="wf-hot", sla=sla)
    await asyncio.sleep(0.1)
    await tracker._check_once()
    assert cancelled == ["wf-hot"]


@pytest.mark.asyncio
async def test_tracker_skips_duplicate_alert_same_level() -> None:
    dispatcher = InMemorySlaAlertDispatcher()
    tracker = SlaTracker(dispatcher=dispatcher)
    sla = SlaPolicy(soft_limit_seconds=0.01, hard_limit_seconds=10.0)
    await tracker.track(workflow_id="wf-d", sla=sla)
    await asyncio.sleep(0.05)
    await tracker._check_once()
    await tracker._check_once()
    # Только один alert даже если check выполнен дважды
    assert len(dispatcher.sent) == 1


@pytest.mark.asyncio
async def test_tracker_untrack_removes() -> None:
    dispatcher = InMemorySlaAlertDispatcher()
    tracker = SlaTracker(dispatcher=dispatcher)
    sla = SlaPolicy(soft_limit_seconds=0.01, hard_limit_seconds=5.0)
    await tracker.track(workflow_id="wf-1", sla=sla)
    assert "wf-1" in tracker.list_tracked()
    await tracker.untrack("wf-1")
    assert "wf-1" not in tracker.list_tracked()
