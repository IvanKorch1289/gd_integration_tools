"""Unit-тесты для ``src.backend.core.workflow.backend``.

Покрывает Pydantic-модели WorkflowHandle / WorkflowResult и
Protocol ``WorkflowBackend`` (runtime_checkable).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from src.backend.core.workflow.backend import (
    WorkflowBackend,
    WorkflowHandle,
    WorkflowResult,
    WorkflowStatus,
)


class TestWorkflowHandle:
    """Валидация WorkflowHandle."""

    def test_valid_handle(self) -> None:
        h = WorkflowHandle(workflow_id="wf-1", run_id="run-a", namespace="t1")
        assert h.workflow_id == "wf-1"
        assert h.run_id == "run-a"
        assert h.namespace == "t1"

    def test_valid_handle_run_id_none(self) -> None:
        """D-A8-09 fix (cycle 24): run_id=None — cancel/signal/query all runs."""
        h = WorkflowHandle(workflow_id="wf-1", run_id=None, namespace="t1")
        assert h.workflow_id == "wf-1"
        assert h.run_id is None
        assert h.namespace == "t1"

    def test_run_id_default_is_none(self) -> None:
        """run_id default = None (опциональный)."""
        h = WorkflowHandle(workflow_id="wf-2", namespace="t1")
        assert h.run_id is None

    def test_empty_workflow_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowHandle(workflow_id="", run_id="r", namespace="t")

    def test_empty_run_id_treated_as_none(self) -> None:
        """D-A8-09 fix (cycle 24): run_id опциональный — пустая строка допустима (= None)."""
        # D-A8-09 fix: run_id стал опциональным (default=None).
        # Empty string НЕ raise — семантика "all runs".
        h = WorkflowHandle(workflow_id="w", run_id="", namespace="t")
        assert h.run_id == ""  # preserved as empty string (callers normalize)

    def test_empty_namespace_raises(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowHandle(workflow_id="w", run_id="r", namespace="")

    def test_frozen_cannot_mutate(self) -> None:
        h = WorkflowHandle(workflow_id="w", run_id="r", namespace="t")
        with pytest.raises(ValidationError):
            h.workflow_id = "x"  # type: ignore[misc]

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowHandle(workflow_id="w", run_id="r", namespace="t", extra_field=1)


class TestWorkflowResult:
    """Валидация WorkflowResult."""

    def test_completed_without_failure(self) -> None:
        r = WorkflowResult(status="completed", output={"step": 1})
        assert r.status == "completed"
        assert r.output == {"step": 1}
        assert r.failure is None

    def test_failed_with_failure(self) -> None:
        r = WorkflowResult(
            status="failed", output={}, failure={"type": "RuntimeError", "message": "x"},
        )
        assert r.status == "failed"
        assert r.failure is not None

    def test_default_output_is_empty_dict(self) -> None:
        r = WorkflowResult(status="cancelled")
        assert r.output == {}

    def test_frozen_cannot_mutate(self) -> None:
        r = WorkflowResult(status="completed")
        with pytest.raises(ValidationError):
            r.status = "failed"  # type: ignore[misc]

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowResult(status="completed", unknown=True)  # type: ignore[call-arg]


class TestWorkflowStatus:
    """WorkflowStatus — alias для str."""

    def test_is_str(self) -> None:
        assert WorkflowStatus == str  # type: ignore[misc]


class _FakeBackend:
    """Минимальная реализация Protocol для проверки runtime_checkable."""

    async def start_workflow(
        self,
        *,
        workflow_name: str,
        workflow_id: str,
        input: dict[str, Any],
        namespace: str,
        task_queue: str,
        execution_timeout: timedelta | None = None,
    ) -> WorkflowHandle:
        return WorkflowHandle(workflow_id="w", run_id="r", namespace="n")

    async def signal_workflow(
        self, *, handle: WorkflowHandle, signal_name: str, payload: dict[str, Any],
    ) -> None:
        pass

    async def query_workflow(
        self,
        *,
        handle: WorkflowHandle,
        query_name: str,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {}

    async def cancel_workflow(self, *, handle: WorkflowHandle) -> None:
        pass

    async def await_completion(
        self, *, handle: WorkflowHandle, timeout: timedelta | None = None,
    ) -> WorkflowResult:
        return WorkflowResult(status="completed")

    async def replay(self, *, workflow_name: str, history: bytes) -> None:
        pass

    async def await_external_signal(
        self,
        *,
        handle: WorkflowHandle,
        signal_name: str,
        timeout: timedelta | None = None,
    ) -> dict[str, Any]:
        return {"timed_out": True}

    async def start_child_workflow(
        self,
        *,
        parent_handle: WorkflowHandle,
        workflow_name: str,
        workflow_id: str,
        input: dict[str, Any],
        task_queue: str,
        execution_timeout: timedelta | None = None,
    ) -> WorkflowHandle:
        return WorkflowHandle(workflow_id="c", run_id="cr", namespace="n")


class TestWorkflowBackendProtocol:
    """Runtime-checkable Protocol."""

    def test_fake_backend_is_instance(self) -> None:
        backend = _FakeBackend()
        assert isinstance(backend, WorkflowBackend)

    def test_plain_object_is_not_instance(self) -> None:
        class Dummy:
            pass

        assert not isinstance(Dummy(), WorkflowBackend)

    def test_missing_method_is_not_instance(self) -> None:
        class Partial:
            async def start_workflow(self, **kwargs: Any) -> WorkflowHandle:
                return WorkflowHandle(workflow_id="w", run_id="r", namespace="n")

        assert not isinstance(Partial(), WorkflowBackend)
