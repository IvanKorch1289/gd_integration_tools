# ruff: noqa: S101
"""Wave C scaffold tests: контракт ``WorkflowBackend`` + ``FakeWorkflowBackend``."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from src.core.workflow import (
    FakeWorkflowBackend,
    WorkflowBackend,
    WorkflowHandle,
    WorkflowResult,
)


class TestWorkflowHandle:
    """Frozen-модель с обязательными полями."""

    def test_construct_minimal(self) -> None:
        handle = WorkflowHandle(workflow_id="wf-1", run_id="r-1", namespace="t-1")
        assert handle.workflow_id == "wf-1"
        assert handle.run_id == "r-1"
        assert handle.namespace == "t-1"

    def test_frozen(self) -> None:
        handle = WorkflowHandle(workflow_id="wf-1", run_id="r-1", namespace="t-1")
        with pytest.raises(ValidationError):
            handle.workflow_id = "wf-2"

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowHandle.model_validate(
                {
                    "workflow_id": "wf-1",
                    "run_id": "r-1",
                    "namespace": "t-1",
                    "extra": "no",
                }
            )

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowHandle(workflow_id="", run_id="r-1", namespace="t-1")


class TestWorkflowResult:
    """Финальный результат с опциональным failure."""

    def test_completed_default(self) -> None:
        result = WorkflowResult(status="completed")
        assert result.status == "completed"
        assert result.output == {}
        assert result.failure is None

    def test_failed_with_details(self) -> None:
        result = WorkflowResult(
            status="failed",
            output={"partial": True},
            failure={"type": "ValueError", "message": "bad input"},
        )
        assert result.failure is not None
        assert result.failure["type"] == "ValueError"


class TestFakeBackendIsProtocol:
    """`FakeWorkflowBackend` должен подпадать под runtime_checkable."""

    def test_runtime_checkable(self) -> None:
        backend = FakeWorkflowBackend()
        assert isinstance(backend, WorkflowBackend)


@pytest.mark.asyncio
class TestFakeBackendBehavior:
    """Сценарии fake-инстанса: start / signal / query / cancel / await."""

    async def test_start_returns_handle(self) -> None:
        backend = FakeWorkflowBackend()
        handle = await backend.start_workflow(
            workflow_name="credit_score",
            workflow_id="wf-1",
            input={"client_id": 42},
            namespace="bank-a",
            task_queue="default",
        )
        assert handle.workflow_id == "wf-1"
        assert handle.namespace == "bank-a"
        assert handle.run_id  # uuid4 hex

    async def test_signal_recorded(self) -> None:
        backend = FakeWorkflowBackend()
        handle = await backend.start_workflow(
            workflow_name="wf",
            workflow_id="wf-1",
            input={},
            namespace="t",
            task_queue="q",
        )
        await backend.signal_workflow(
            handle=handle, signal_name="approve", payload={"by": "ops"}
        )
        assert backend.signals_for(handle) == [("approve", {"by": "ops"})]

    async def test_query_returns_static(self) -> None:
        backend = FakeWorkflowBackend(query_handlers={"status": {"phase": "review"}})
        handle = await backend.start_workflow(
            workflow_name="wf",
            workflow_id="wf-1",
            input={},
            namespace="t",
            task_queue="q",
        )
        result = await backend.query_workflow(handle=handle, query_name="status")
        assert result == {"phase": "review"}

    async def test_query_unknown_returns_empty(self) -> None:
        backend = FakeWorkflowBackend()
        handle = await backend.start_workflow(
            workflow_name="wf",
            workflow_id="wf-1",
            input={},
            namespace="t",
            task_queue="q",
        )
        assert await backend.query_workflow(handle=handle, query_name="x") == {}

    async def test_cancel_marks_instance(self) -> None:
        backend = FakeWorkflowBackend()
        handle = await backend.start_workflow(
            workflow_name="wf",
            workflow_id="wf-1",
            input={},
            namespace="t",
            task_queue="q",
        )
        await backend.cancel_workflow(handle=handle)
        assert backend.is_cancelled(handle) is True
        result = await backend.await_completion(handle=handle)
        assert result.status == "cancelled"

    async def test_await_default_result(self) -> None:
        backend = FakeWorkflowBackend()
        handle = await backend.start_workflow(
            workflow_name="wf",
            workflow_id="wf-1",
            input={},
            namespace="t",
            task_queue="q",
        )
        result = await backend.await_completion(
            handle=handle, timeout=timedelta(seconds=1)
        )
        assert result.status == "completed"
        assert result.output == {}

    async def test_await_custom_result_via_helper(self) -> None:
        backend = FakeWorkflowBackend()
        handle = await backend.start_workflow(
            workflow_name="wf",
            workflow_id="wf-1",
            input={},
            namespace="t",
            task_queue="q",
        )
        backend.set_result(handle, WorkflowResult(status="failed", output={"step": 3}))
        result = await backend.await_completion(handle=handle)
        assert result.status == "failed"
        assert result.output == {"step": 3}

    async def test_replay_is_noop(self) -> None:
        backend = FakeWorkflowBackend()
        await backend.replay(workflow_name="wf", history=b"")

    async def test_unknown_handle_raises(self) -> None:
        backend = FakeWorkflowBackend()
        ghost = WorkflowHandle(
            workflow_id="wf-x", run_id="missing", namespace="t"
        )
        with pytest.raises(KeyError):
            await backend.signal_workflow(
                handle=ghost, signal_name="s", payload={}
            )
