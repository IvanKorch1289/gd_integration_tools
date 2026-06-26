# ruff: noqa: S101
"""Unit tests for WorkflowBackend Protocol and Pydantic models."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from src.backend.core.workflow.backend import (
    WorkflowBackend,
    WorkflowHandle,
    WorkflowResult,
)


class TestWorkflowHandle:
    def test_all_fields_required(self) -> None:
        handle = WorkflowHandle(workflow_id="wf-1", run_id="r-1", namespace="ns-1")
        assert handle.workflow_id == "wf-1"
        assert handle.run_id == "r-1"
        assert handle.namespace == "ns-1"

    def test_missing_workflow_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowHandle(run_id="r-1", namespace="ns-1")

    def test_missing_run_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowHandle(workflow_id="wf-1", namespace="ns-1")

    def test_missing_namespace_raises(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowHandle(workflow_id="wf-1", run_id="r-1")

    def test_empty_workflow_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowHandle(workflow_id="", run_id="r-1", namespace="ns-1")

    def test_empty_run_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowHandle(workflow_id="wf-1", run_id="", namespace="ns-1")

    def test_empty_namespace_raises(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowHandle(workflow_id="wf-1", run_id="r-1", namespace="")

    def test_frozen(self) -> None:
        handle = WorkflowHandle(workflow_id="wf-1", run_id="r-1", namespace="ns-1")
        with pytest.raises(ValidationError):
            handle.workflow_id = "wf-2"

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowHandle(
                workflow_id="wf-1", run_id="r-1", namespace="ns-1", extra_field="no"
            )


class TestWorkflowResult:
    def test_default_values(self) -> None:
        result = WorkflowResult(status="completed")
        assert result.status == "completed"
        assert result.output == {}
        assert result.failure is None

    def test_with_failure(self) -> None:
        result = WorkflowResult(
            status="failed",
            output={"partial": True},
            failure={"type": "ValueError", "message": "bad input"},
        )
        assert result.failure is not None
        assert result.failure["type"] == "ValueError"

    def test_missing_status_raises(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowResult()


class TestWorkflowBackendProtocol:
    def test_fake_backend_is_subclass(self) -> None:
        from src.backend.core.workflow.fake_backend import FakeWorkflowBackend

        assert issubclass(FakeWorkflowBackend, WorkflowBackend)

    def test_fake_backend_instance_is_instance(self) -> None:
        from src.backend.core.workflow.fake_backend import FakeWorkflowBackend

        backend = FakeWorkflowBackend()
        assert isinstance(backend, WorkflowBackend)

    def test_custom_fake_backend_is_instance_and_subclass(self) -> None:
        class FakeBackend:
            async def start_workflow(
                self,
                *,
                workflow_name: str,
                workflow_id: str,
                input: dict[str, Any],
                namespace: str,
                task_queue: str,
                execution_timeout: timedelta | None = None,
            ) -> WorkflowHandle: ...

            async def signal_workflow(
                self,
                *,
                handle: WorkflowHandle,
                signal_name: str,
                payload: dict[str, Any],
            ) -> None: ...

            async def query_workflow(
                self,
                *,
                handle: WorkflowHandle,
                query_name: str,
                args: dict[str, Any] | None = None,
            ) -> dict[str, Any]: ...

            async def cancel_workflow(self, *, handle: WorkflowHandle) -> None: ...

            async def await_completion(
                self, *, handle: WorkflowHandle, timeout: timedelta | None = None
            ) -> WorkflowResult: ...

            async def replay(self, *, workflow_name: str, history: bytes) -> None: ...

            async def compensate_workflow(
                self,
                *,
                handle: WorkflowHandle,
                request: "CompensateWorkflowRequest",
            ) -> None: ...

        assert issubclass(FakeBackend, WorkflowBackend)
        assert isinstance(FakeBackend(), WorkflowBackend)
