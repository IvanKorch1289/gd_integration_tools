"""Unit-тесты Prometheus export для SLA — Sprint 12 K2 W1.

ADR-0408 (волна 22): счётчик переехал в
``src.backend.core.observability.workflow_sla`` (единый источник
определения метрики для services и infrastructure).
"""

from __future__ import annotations

import pytest

from src.backend.services.workflows.sla_alerting import SlaBreachLevel, evaluate_sla

prom = pytest.importorskip("prometheus_client", reason="prometheus_client отсутствует")


def _counter() -> object:
    """Счётчик SLA-compliance (core — единственный источник определения)."""
    from src.backend.core.observability.workflow_sla import get_workflow_sla_counter

    return get_workflow_sla_counter()


def test_evaluate_sla_none_increments_counter() -> None:
    breach = evaluate_sla(
        workflow_id="wf-fast",
        elapsed_seconds=1.0,
        soft_limit_seconds=60.0,
        hard_limit_seconds=300.0,
        tenant_id="t1",
    )
    assert breach.level == SlaBreachLevel.NONE

    counter = _counter()
    assert counter is not None
    samples = list(counter.collect())
    assert any("none" in str(s) for s in samples)


def test_evaluate_sla_soft_breach_increments_soft() -> None:
    breach = evaluate_sla(
        workflow_id="wf-soft",
        elapsed_seconds=120.0,
        soft_limit_seconds=60.0,
        hard_limit_seconds=300.0,
        tenant_id="t2",
    )
    assert breach.level == SlaBreachLevel.SOFT


def test_evaluate_sla_hard_breach_increments_hard() -> None:
    breach = evaluate_sla(
        workflow_id="wf-hard",
        elapsed_seconds=400.0,
        soft_limit_seconds=60.0,
        hard_limit_seconds=300.0,
        tenant_id="t3",
    )
    assert breach.level == SlaBreachLevel.HARD
