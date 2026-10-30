"""ADR-0403: мёртвый SLA-трекер удалён, состояние описано честно.

Дефект (до фикса)
-----------------
``SlaTracker`` (``src/backend/services/workflows/sla_alerting.py``) не был
инстанцирован **нигде** в ``src/``: ни в lifespan, ни в worker'ах, ни в
composition root. ``WorkflowFacade`` принимал ``sla_tracker`` только как
опциональный параметр, а сам фасад в ``src/`` не создавался. ADR-0396
утверждал, что «SLA-политика перестала быть инертной» — трекинга SLA в
рантайме не было.

Решение волны 21 — **удалить** исполнитель трекинга (класс
``SlaTracker`` + протокол ``SlaAlertDispatcher`` + его in-memory
реализацию) и явно зафиксировать в ADR-0403 и docstring'ах, что:

* эскалация по SLA (email/Slack) **не реализована**;
* поднять исполнитель в composition root нельзя в этом кластере:
  фасад не находится на production-пути старта workflow
  (``dsl/engine/processors/invoke_workflow.py`` стартует workflow напрямую
  через backend), а канала эскалации (email/Slack) в репозитории нет;
* чистая функция оценки ``evaluate_sla`` (метрика
  ``workflow_sla_compliance_total``) остаётся — она не привязана к
  исполнителю и используется Grafana-дашбордом.

Ожидание
--------
* ``SlaTracker``/``SlaAlertDispatcher``/``InMemorySlaAlertDispatcher``
  отсутствуют в модуле;
* ``WorkflowFacade`` больше не принимает ``sla_tracker`` и не ссылается на
  трекер;
* docstring модуля и ADR-0403 фиксируют, что SLA-алертинг не реализован
  (идентификатор owner-задачи ``GAP-WF-4.5``).
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from src.backend.services.workflows import facade as facade_module
from src.backend.services.workflows import sla_alerting

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
ADR_PATH = REPO_ROOT / "docs" / "adr" / "0403-workflow-sla-dlq-and-prod-validator.md"
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


def test_module_docstring_declares_sla_alerting_not_implemented() -> None:
    """Docstring модуля фиксирует честное состояние (owner-задача)."""
    docstring = sla_alerting.__doc__ or ""
    assert OWNER_TASK_ID in docstring, (
        "docstring модуля должен ссылаться на owner-задачу " + OWNER_TASK_ID
    )
    assert "не реализован" in docstring.lower()


def test_adr_documents_sla_alerting_decision() -> None:
    """ADR-0403 описывает решение по SLA-трекингу и owner-задачу."""
    text = ADR_PATH.read_text(encoding="utf-8")
    assert OWNER_TASK_ID in text
    assert "SlaTracker" in text
