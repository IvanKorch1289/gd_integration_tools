"""ADR-0408 (волна 22): runbook-гейт для workflow-DLQ и SLA-алертинга.

Дефект (до фикса)
-----------------
* runbook ``docs/runbooks/hitl-stuck-workflow.md`` утверждал, что
  SLA-алертинг «не реализован», хотя gap-WF-4.5 закрыт кодом
  (метрика ``workflow_sla_compliance_total`` + alert-рул);
* alert-правила не было ни в одном документе репозитория;
* ADR-0408 отсутствовал.

Ожидание
--------
* ADR-0408 существует и содержит обязательные секции;
* в ``docs/ops/`` есть alert-рул с Prometheus-правилами по обеим
  метрикам и явным порогом;
* runbook описывает фактическую семантику (терминальный FAILED + DLQ +
  метрика) и не утверждает «не реализован».
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
ADR_0408 = REPO_ROOT / "docs" / "adr" / "0408-workflow-dlq-contract-and-sla-alerting.md"
ALERTS_DOC = REPO_ROOT / "docs" / "ops" / "workflow-sla-alerts.md"
HITL_RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "hitl-stuck-workflow.md"


def test_adr_0408_exists_with_required_sections() -> None:
    """ADR-0408 оформлен по формату репозитория."""
    assert ADR_0408.exists(), "ADR-0408 должен существовать"
    text = ADR_0408.read_text(encoding="utf-8")

    assert text.startswith("# ADR-0408 — ")
    assert "* Статус: Accepted" in text
    for section in (
        "## Контекст",
        "## Решение",
        "## Альтернативы",
        "## Последствия",
        "## Проверка",
        "## Связи",
    ):
        assert section in text, f"ADR-0408: нет секции {section}"


def test_adr_0408_describes_dlq_contract_and_sla_metric() -> None:
    """ADR-0408 описывает DLQ-контракт и закрытие GAP-WF-4.5."""
    text = ADR_0408.read_text(encoding="utf-8")

    assert "GAP-WF-4.5" in text
    assert "workflow_sla_compliance_total" in text
    assert "workflow_dlq_publish_total" in text
    assert "retries_exhausted" in text.lower()
    assert "docs/ops/workflow-sla-alerts.md" in text


def test_alerts_doc_has_prometheus_rules_for_both_metrics() -> None:
    """В docs/ops есть Prometheus-правила по обеим метрикам."""
    assert ALERTS_DOC.exists(), "alert-рул должен лежать в docs/ops/"
    text = ALERTS_DOC.read_text(encoding="utf-8")

    assert "groups:" in text
    assert "workflow_sla_compliance_total" in text
    assert "workflow_dlq_publish_total" in text
    assert "alert:" in text
    assert "severity:" in text


def test_alerts_doc_states_threshold_source() -> None:
    """Порог нарушения берётся из настроек SLO роутов."""
    text = ALERTS_DOC.read_text(encoding="utf-8")

    assert "route.toml::slo" in text
    assert "timeout_ms" in text
    assert "error budget" in text.lower()


def test_hitl_runbook_reflects_actual_semantics() -> None:
    """Runbook: терминальный FAILED + DLQ + метрика, без «не реализован»."""
    text = HITL_RUNBOOK.read_text(encoding="utf-8")

    assert "не реализован" not in text.lower()
    assert 'transport="workflow"' in text or "transport=workflow" in text
    assert "workflow_sla_compliance_total" in text
    assert "workflow-sla-alerts.md" in text
    assert "ADR-0408" in text
