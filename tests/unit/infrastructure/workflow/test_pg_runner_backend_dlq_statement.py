"""ADR-0403 → ADR-0408: workflow-DLQ — контракт реализован для шагов.

Дефект (до фикса волны 21)
--------------------------
``PgRunnerWorkflowBackend.replay()`` всегда бросал ``NotImplementedError``,
и в документации это выглядело как «нереализованный DLQ для workflow».
На деле исчерпание retry-бюджета шага давало терминальный ``FAILED`` +
метрику, но **без** записи в DLQ — исчерпанный шаг был потерян.

Решение волны 22 (ADR-0408)
---------------------------
* исчерпанный шаг попадает в messaging-DLQ (``DLQEnvelope``,
  ``transport="workflow"``) с route_id / step / attempts / причиной /
  tenant и payload-метаданными без значений данных;
* ``dlq_id`` детерминирован → повторный запуск не дублирует запись;
* ``replay()`` реализован как **переигровка исчерпанного шага** по
  DLQ-записи (сброс retry-бюджета + возврат инстанса в ``pending``) —
  ветка ``NotImplementedError`` заменена реализацией.
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


def test_module_docstring_states_workflow_dlq_contract() -> None:
    """Docstring модуля фиксирует DLQ-контракт исчерпанных шагов."""
    docstring = pg_module.__doc__ or ""
    assert docstring, "модуль должен иметь docstring"
    assert "DLQ" in docstring
    assert "ADR-0408" in docstring
    assert 'transport="workflow"' in docstring


@pytest.mark.asyncio
async def test_replay_implements_dlq_replay_not_not_implemented() -> None:
    """``replay()`` реализован (DLQ-replay), а не ``NotImplementedError``."""
    backend = PgRunnerWorkflowBackend.__new__(PgRunnerWorkflowBackend)

    with pytest.raises(ValueError) as exc_info:
        await backend.replay(workflow_name="wf", history=b"")

    message = str(exc_info.value)
    assert "DLQ" in message
    assert "workflow_id" in message


def test_replay_docstring_mentions_dlq_status() -> None:
    """Docstring ``replay()`` описывает DLQ-replay исчерпанного шага."""
    docstring = inspect.getdoc(PgRunnerWorkflowBackend.replay) or ""

    assert "DLQ" in docstring
    assert "ADR-0408" in docstring
    assert "attempts_reset" in docstring


def test_workflows_doc_mentions_workflow_dlq() -> None:
    """``docs/workflows/index.md`` упоминает workflow-DLQ."""
    text = WORKFLOWS_DOC.read_text(encoding="utf-8")

    assert "DLQ" in text
    assert "ADR-0403" in text or "OWNER_TASKS" in text


def test_dlq_runbook_scopes_itself_to_messaging() -> None:
    """Runbook DLQ явно ограничен messaging-транспортами."""
    text = DLQ_RUNBOOK.read_text(encoding="utf-8")

    assert "workflow" in text.lower(), (
        "runbook должен явно разграничивать scope: messaging-DLQ и workflow-шаги"
    )
