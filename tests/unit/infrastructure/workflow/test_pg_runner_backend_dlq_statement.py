"""ADR-0403: workflow-DLQ — честная фиксация «не реализовано».

Дефект (до фикса)
-----------------
``PgRunnerWorkflowBackend.replay()`` (``pg_runner_backend.py:250``) всегда
бросает ``NotImplementedError``, и в документации это выглядело как
«нереализованный DLQ для workflow». На деле:

* ``replay()`` — Temporal-совместимый **replay-gate** (детерминизм
  history), а не DLQ; pg-runner восстанавливает состояние
  event-sourcing'ом из ``workflow_events``;
* workflow **не имеет** DLQ: ``workflow_events`` — append-only event log
  инстанса, а не очередь недоставленных сообщений;
* исчерпание retry-бюджета шага приводит к терминальному ``FAILED``
  (``WorkflowStatus.failed`` + метрика + audit-строка), но **не** к записи
  в DLQ и **не** к возможности переигровки.

Требование волны: не откатывая формулировку про messaging-DLQ (волна 20),
зафиксировать в коде и документации, что workflow-DLQ не реализован, и
завести owner-задачу.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from src.backend.infrastructure.workflow import pg_runner_backend as pg_module
from src.backend.infrastructure.workflow.pg_runner_backend import (
    PgRunnerWorkflowBackend,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOWS_DOC = REPO_ROOT / "docs" / "workflows" / "index.md"
DLQ_RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "dlq-replay.md"


def test_module_docstring_states_workflow_has_no_dlq() -> None:
    """Docstring модуля фиксирует: у workflow нет DLQ."""
    docstring = pg_module.__doc__ or ""
    assert docstring, "модуль должен иметь docstring"
    assert "DLQ" in docstring
    assert "не реализован" in docstring.lower()


@pytest.mark.asyncio
async def test_replay_error_message_is_explicit_about_dlq() -> None:
    """``replay()`` объясняет, что это replay-gate, а не DLQ."""
    backend = PgRunnerWorkflowBackend.__new__(PgRunnerWorkflowBackend)

    with pytest.raises(NotImplementedError) as exc_info:
        await backend.replay(workflow_name="wf", history=b"{}")

    message = str(exc_info.value)
    assert "Temporal" in message
    assert "DLQ" in message
    assert "ADR-0403" in message


def test_replay_docstring_mentions_dlq_status() -> None:
    """Docstring ``replay()`` разделяет replay-gate и DLQ."""
    docstring = inspect.getdoc(PgRunnerWorkflowBackend.replay) or ""

    assert "DLQ" in docstring
    assert "ADR-0403" in docstring


def test_workflows_doc_states_no_workflow_dlq() -> None:
    """``docs/workflows/index.md`` фиксирует отсутствие workflow-DLQ."""
    text = WORKFLOWS_DOC.read_text(encoding="utf-8")

    assert "DLQ" in text
    assert "ADR-0403" in text or "OWNER_TASKS" in text


def test_dlq_runbook_scopes_itself_to_messaging() -> None:
    """Runbook DLQ явно ограничен messaging'ом — workflow-шаги не в его scope."""
    text = DLQ_RUNBOOK.read_text(encoding="utf-8")

    assert "workflow" in text.lower(), (
        "runbook должен явно сказать, что workflow-шаги не попадают в DLQ"
    )
