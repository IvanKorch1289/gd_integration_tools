"""Unit-тесты для src/testkit/workflow_runner.py (cycle 33 L10 cycle 1).

WorkflowRunner — thin wrapper over DurableWorkflowRunner, используется
в unit-тестах для запуска workflow без реального Temporal/Postgres.
``testkit`` package — критическая test-инфраструктура, используется
в сотнях тестов. Без тестов — регрессии в API (например, breaking
change в сигнатуре ``run()``) пройдут незаметно.
"""

# ruff: noqa: S101

from __future__ import annotations

from datetime import timedelta

import pytest

from src.backend.core.workflow import FakeWorkflowBackend, WorkflowResult
from src.testkit.workflow_runner import WorkflowRunner, WorkflowRunResult


@pytest.fixture
def runner() -> WorkflowRunner:
    """Default WorkflowRunner без предустановленных results."""
    return WorkflowRunner()


def test_workflow_run_result_dataclass_contract() -> None:
    """WorkflowRunResult: frozen dataclass с output/status/failure полями."""
    result = WorkflowRunResult(
        output={"score": 0.95},
        status="completed",
        failure=None,
    )
    assert result.output == {"score": 0.95}
    assert result.status == "completed"
    assert result.failure is None

    # Frozen — mutation raise.
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        result.status = "modified"  # type: ignore[misc]


def test_workflow_runner_init_creates_fake_backend() -> None:
    """WorkflowRunner.__init__ создаёт FakeWorkflowBackend instance."""
    runner = WorkflowRunner()
    assert isinstance(runner.backend, FakeWorkflowBackend)


def test_workflow_runner_init_accepts_default_result() -> None:
    """default_result пробрасывается в FakeWorkflowBackend.

    Backend хранит под underscore-prefixed атрибутом ``_default_result``
    (private, но именно через него await_completion возвращает fallback).
    """
    result = WorkflowResult(output={"ok": True}, status="completed")
    runner = WorkflowRunner(default_result=result)
    assert runner.backend._default_result is result


def test_workflow_runner_init_accepts_query_handlers() -> None:
    """query_handlers пробрасываются в FakeWorkflowBackend (``_query_handlers``)."""
    qh = {"get_status": {"phase": "running"}}
    runner = WorkflowRunner(query_handlers=qh)
    assert runner.backend._query_handlers == qh


@pytest.mark.asyncio
async def test_run_returns_workflow_run_result() -> None:
    """runner.run() возвращает WorkflowRunResult, не raw WorkflowResult.

    Использует default_result в constructor (set_result + start — race
    condition: start создаёт instance, set_result сохраняет в instance,
    но run() создаёт НОВЫЙ instance).
    """
    result = WorkflowResult(output={"x": 1}, status="completed")
    runner = WorkflowRunner(default_result=result)

    workflow_result = await runner.run(
        workflow_name="test_wf", workflow_id="wf-1", input={"k": "v"}
    )

    assert isinstance(workflow_result, WorkflowRunResult)
    assert workflow_result.output == {"x": 1}
    assert workflow_result.status == "completed"
    assert workflow_result.failure is None


@pytest.mark.asyncio
async def test_run_passes_args_to_backend() -> None:
    """run() пробрасывает все kwargs (namespace, task_queue, timeout) в backend."""
    runner = WorkflowRunner()

    await runner.run(
        workflow_name="ns_wf",
        workflow_id="ns-1",
        input={"k": "v"},
        namespace="prod",
        task_queue="high-priority",
        execution_timeout=timedelta(seconds=30),
    )

    # Verify instance was created with correct args.
    instances = list(runner.backend._instances.values())
    assert len(instances) == 1
    instance = instances[0]
    assert instance.handle.namespace == "prod"
    assert instance.task_queue == "high-priority"
    assert instance.execution_timeout == timedelta(seconds=30)


@pytest.mark.asyncio
async def test_run_propagates_failure() -> None:
    """Если default_result.status == failed → WorkflowRunResult.failure set."""
    failure = {"error": "TestError", "message": "boom"}
    default = WorkflowResult(output={}, status="failed", failure=failure)
    runner = WorkflowRunner(default_result=default)

    result = await runner.run(
        workflow_name="fail_wf", workflow_id="fail-1", input={}
    )
    assert result.status == "failed"
    assert result.failure == failure


@pytest.mark.asyncio
async def test_start_returns_handle_with_correct_workflow_id() -> None:
    """runner.start() возвращает WorkflowHandle с правильным workflow_id."""
    runner = WorkflowRunner()

    handle = await runner.start(
        workflow_name="async_wf", workflow_id="async-1", input={"x": 1}
    )
    # Handle имеет атрибуты workflow_id и namespace.
    assert handle.workflow_id == "async-1"
    assert handle.namespace == "test"  # default


@pytest.mark.asyncio
async def test_start_then_set_result_then_await() -> None:
    """start() + set_result + await_completion через backend — корректный 2-step pattern."""
    runner = WorkflowRunner()

    handle = await runner.start(
        workflow_name="two_step_wf", workflow_id="two-1", input={}
    )
    runner.backend.set_result(
        handle, WorkflowResult(output={"two_step": True}, status="completed")
    )
    # await через backend напрямую.
    result = await runner.backend.await_completion(handle=handle)
    assert result.output == {"two_step": True}


def test_workflow_runner_backend_attribute_accessible() -> None:
    """runner.backend — публичный атрибут для test introspection."""
    runner = WorkflowRunner()
    assert hasattr(runner, "backend")
    # Имеет ожидаемые методы FakeWorkflowBackend.
    assert hasattr(runner.backend, "set_result")
    assert hasattr(runner.backend, "await_completion")
    assert hasattr(runner.backend, "signal_workflow")
    assert hasattr(runner.backend, "query_workflow")
