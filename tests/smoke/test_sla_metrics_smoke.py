"""S36 w1 — Smoke test: SLA metrics (workflow SLA evaluation).

Проверяет критический путь:
- evaluate_sla возвращает правильный breach level;
- SlaBreachRecord.to_dict() сериализуется.

.. note::
   ADR-0403 (волна 21): исполнитель SLA-трекинга (``SlaTracker``) и
   протокол диспетчера удалены как мёртвый код (owner-задача GAP-WF-4.5) —
   smoke-тесты диспетчера удалены вместе с ними.
"""

from __future__ import annotations

from src.backend.services.workflows.sla_alerting import (
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
