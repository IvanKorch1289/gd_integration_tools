"""ADR-0403 → ADR-0408: мёртвый SLA-трекер удалён, метрика эмитится в рантайме.

Дефект (до фикса волны 21)
--------------------------
``SlaTracker`` (``src/backend/services/workflows/sla_alerting.py``) не был
инстанцирован **нигде** в ``src/``: ни в lifespan, ни в worker'ах, ни в
composition root. ``WorkflowFacade`` принимал ``sla_tracker`` только как
опциональный параметр, а сам фасад в ``src/`` не создавался. ADR-0396
утверждал, что «SLA-политика перестала быть инертной» — трекинга SLA в
рантайме не было.

Решение волны 21 — **удалить** исполнитель трекинга (класс
``SlaTracker`` + протокол ``SlaAlertDispatcher`` + его in-memory
реализацию) и явно зафиксировать в ADR-0403 и docstring'ах, что
эскалация по SLA (email/Slack) **не реализована**.

Решение волны 22 (ADR-0408) — **GAP-WF-4.5 закрыт метрикой + alert-рулом**:
оценка SLA выполняется в точке терминального перехода workflow'а
(pg-runner runner), счётчик ``workflow_sla_compliance_total{level}``
эмитится в рантайме; канал эскалации (email/Slack) по-прежнему
отсутствует — уведомление приходит через Prometheus-алерт.

Ожидание
--------
* ``SlaTracker``/``SlaAlertDispatcher``/``InMemorySlaAlertDispatcher``
  отсутствуют в модуле;
* ``WorkflowFacade`` больше не принимает ``sla_tracker`` и не ссылается на
  трекер;
* docstring модуля фиксирует честное состояние: SLA-алертинг — это
  метрика + alert-рул (ADR-0408), эскалация email/Slack — не реализована;
* owner-задача ``GAP-WF-4.5`` закрыта кодом (ссылка в docstring'е).
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from src.backend.services.workflows import facade as facade_module
from src.backend.services.workflows import sla_alerting

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
ADR_0403 = REPO_ROOT / "docs" / "adr" / "0403-workflow-sla-dlq-and-prod-validator.md"
ADR_0408 = REPO_ROOT / "docs" / "adr" / "0408-workflow-dlq-contract-and-sla-alerting.md"
OWNER_TASK_ID = "GAP-WF-4.5"


def test_sla_tracker_class_is_removed() -> None:
    """Класс ``SlaTracker`` удалён из ``sla_alerting``."""
    assert not hasattr(sla_alerting, "SlaTracker"), (
        "SlaTracker не инстанцируется нигде в src/ — мёртвый код (ADR-0403)"
    )


def test_sla_dispatcher_protocol_is_removed() -> None:
    """Протокол диспетчера и его in-memory реализация удалены."""
    assert not hasattr(sla_alerting, "SlaAlertDispatcher")
    assert not hasattr(sla_alerting, "InMemorySlaAlertDispatcher")


def test_facade_has_no_sla_tracker_parameter() -> None:
    """``WorkflowFacade`` больше не принимает ``sla_tracker``."""
    parameters = inspect.signature(facade_module.WorkflowFacade.__init__).parameters
    assert "sla_tracker" not in parameters
    assert "sla_resolver" in parameters, (
        "SLA hard-limit как бюджет времени остаётся в фасаде (ADR-0396)"
    )


def test_facade_source_does_not_reference_sla_tracker() -> None:
    """Фасад не использует удалённый трекер (только упоминание в docstring)."""
    source = inspect.getsource(facade_module)
    assert "from src.backend.services.workflows.sla_alerting import" not in source
    assert "self._sla_tracker" not in source
    assert "_track_sla" not in source
    assert "_untrack_sla" not in source


def test_module_docstring_declares_metric_based_sla_alerting() -> None:
    """Docstring модуля фиксирует: SLA-алертинг = метрика + alert-рул."""
    docstring = sla_alerting.__doc__ or ""
    assert OWNER_TASK_ID in docstring, (
        "docstring модуля должен ссылаться на owner-задачу " + OWNER_TASK_ID
    )
    assert "ADR-0408" in docstring, "docstring должен ссылаться на ADR-0408"
    assert "workflow_sla_compliance_total" in docstring, (
        "docstring должен называть эмитируемую метрику"
    )
    assert "не реализовано" in docstring.lower(), (
        "эскалация email/Slack по-прежнему не реализована — это надо сказать"
    )


def test_adr_documents_sla_alerting_decision() -> None:
    """ADR-0403 описывает решение по SLA-трекингу и owner-задачу."""
    text = ADR_0403.read_text(encoding="utf-8")
    assert OWNER_TASK_ID in text
    assert "SlaTracker" in text


def test_adr_0408_closes_gap_with_metric_and_alert_rule() -> None:
    """ADR-0408 закрывает GAP-WF-4.5 кодом (метрика + alert-рул)."""
    text = ADR_0408.read_text(encoding="utf-8")
    assert OWNER_TASK_ID in text
    assert "workflow_sla_compliance_total" in text
    assert "workflow_dlq_publish_total" in text
    assert "docs/ops/workflow-sla-alerts.md" in text
