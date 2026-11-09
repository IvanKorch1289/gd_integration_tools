"""ADR-0429 — неожиданное исключение в runner'е переводит инстанс в ``failed``.

Контекст дефекта
----------------
``DurableWorkflowRunner._execute_one`` ловил неожиданное исключение и только
логировал его. Инстанс при этом оставался в статусе ``running``: backup-poll
подхватывал его снова и снова (счётчик попыток рос), DLQ и компенсация не
срабатывали — то есть «зависший» workflow жил бесконечно.

Теперь инстанс переводится в терминальный ``failed`` с текстом ошибки; если и
это не удалось (например, БД недоступна) — инстанс подхватит backup-poll после
восстановления БД.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.domain.models.workflow_instance import WorkflowStatus
from src.backend.infrastructure.workflow.runner import (
    DurableWorkflowRunner,
    RunnerConfig,
)

pytestmark = pytest.mark.unit


def _build_runner() -> tuple[DurableWorkflowRunner, MagicMock]:
    """Runner с полностью замоканными store'ами."""
    cfg = RunnerConfig(worker_id="test-worker", max_concurrent=1)
    state_store = MagicMock(name="state_store")
    state_store.update_status = AsyncMock(name="update_status")
    state_store.try_lock = AsyncMock(name="try_lock", return_value=True)
    state_store.get = AsyncMock(name="get", return_value=None)
    state_store.unlock = AsyncMock(name="unlock", return_value=True)
    state_store.list_pending = AsyncMock(name="list_pending", return_value=[])
    event_store = MagicMock(name="event_store")
    event_store.read_events = AsyncMock(name="read_events", return_value=[])
    event_store.append = AsyncMock(name="append")
    executor = MagicMock(name="executor")
    executor.execute_next = AsyncMock(name="execute_next")
    runner = DurableWorkflowRunner(
        config=cfg, executor=executor, state_store=state_store, event_store=event_store
    )
    return runner, state_store


@pytest.mark.asyncio
async def test_unexpected_error_marks_instance_failed() -> None:
    """Неожиданное исключение → ``update_status(..., failed)``."""
    runner, state_store = _build_runner()
    runner._run_step = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]

    await runner._execute_one(MagicMock(name="workflow_id"))

    state_store.update_status.assert_awaited()
    args = state_store.update_status.await_args.args
    assert args[1] == WorkflowStatus.failed
    assert "boom" in (state_store.update_status.await_args.kwargs.get("error") or "")


@pytest.mark.asyncio
async def test_status_update_failure_does_not_crash_task() -> None:
    """Если статус обновить не удалось (БД недоступна) — задача не падает."""
    runner, state_store = _build_runner()
    runner._run_step = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
    state_store.update_status = AsyncMock(side_effect=OSError("db down"))

    await runner._execute_one(MagicMock(name="workflow_id"))  # не должно бросать
