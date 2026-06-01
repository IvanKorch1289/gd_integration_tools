"""S36 w1 — Smoke test: SLA metrics (workflow SLA alerting).

Проверяет критический путь:
- evaluate_sla возвращает правильный breach level;
- SlaBreachRecord.to_dict() сериализуется;
- InMemorySlaAlertDispatcher накапливает события.
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio

from src.backend.services.workflows.sla_alerting import (
    InMemorySlaAlertDispatcher,
    SlaBreachLevel,
    SlaBreachRecord,
    evaluate_sla,
)


def test_evaluate_sla_no_breach() -> None:
    """elapsed < soft_limit → level=NONE."""
    record = evaluate_sla(
        workflow_id="smoke.sla.ok",
        elapsed_seconds=10.0,
        soft_limit_seconds=60.0,
        hard_limit_seconds=120.0,
    )

    assert record.level == SlaBreachLevel.NONE


def test_evaluate_sla_soft_breach() -> None:
    """soft_limit <= elapsed < hard_limit → level=SOFT."""
    record = evaluate_sla(
        workflow_id="smoke.sla.soft",
        elapsed_seconds=80.0,
        soft_limit_seconds=60.0,
        hard_limit_seconds=120.0,
    )

    assert record.level == SlaBreachLevel.SOFT


def test_evaluate_sla_hard_breach() -> None:
    """elapsed >= hard_limit → level=HARD."""
    record = evaluate_sla(
        workflow_id="smoke.sla.hard",
        elapsed_seconds=150.0,
        soft_limit_seconds=60.0,
        hard_limit_seconds=120.0,
    )

    assert record.level == SlaBreachLevel.HARD


def test_sla_breach_record_to_dict() -> None:
    """SlaBreachRecord.to_dict() возвращает dict с workflow_id + level."""
    record = SlaBreachRecord(
        workflow_id="smoke.sla.dict",
        level=SlaBreachLevel.SOFT,
        elapsed_seconds=80.0,
        soft_limit=60.0,
        hard_limit=120.0,
    )

    data = record.to_dict()

    assert isinstance(data, dict)
    assert data["workflow_id"] == "smoke.sla.dict"
    assert data["level"] == SlaBreachLevel.SOFT


def test_in_memory_dispatcher_accumulates_events() -> None:
    """InMemorySlaAlertDispatcher.dispatch() сохраняет события в .sent."""
    dispatcher = InMemorySlaAlertDispatcher()
    record = SlaBreachRecord(
        workflow_id="smoke.sla.dispatcher",
        level=SlaBreachLevel.HARD,
        elapsed_seconds=200.0,
        soft_limit=60.0,
        hard_limit=120.0,
    )

    asyncio.run(dispatcher.dispatch(breach=record, email=None, slack=None))

    assert len(dispatcher.sent) == 1
    assert dispatcher.sent[0]["breach"]["workflow_id"] == "smoke.sla.dispatcher"


def test_in_memory_dispatcher_isolated_per_instance() -> None:
    """Каждый InMemorySlaAlertDispatcher — изолированное хранилище."""
    disp_a = InMemorySlaAlertDispatcher()
    disp_b = InMemorySlaAlertDispatcher()
    record = SlaBreachRecord(
        workflow_id="smoke.sla.iso",
        level=SlaBreachLevel.SOFT,
        elapsed_seconds=70.0,
        soft_limit=60.0,
        hard_limit=120.0,
    )

    asyncio.run(disp_a.dispatch(breach=record, email=None, slack=None))

    assert len(disp_a.sent) == 1
    assert len(disp_b.sent) == 0
