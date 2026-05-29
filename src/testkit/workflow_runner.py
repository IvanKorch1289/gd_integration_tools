"""WorkflowRunner — thin wrapper over DurableWorkflowRunner for unit tests.

K5 S19 W3 (S-L10-1). Provides a simplified test interface for workflow
execution without requiring a real Temporal cluster or Postgres database.

:class:`WorkflowRunner` wraps :class:`DurableWorkflowRunner
<src.backend.infrastructure.workflow.runner.DurableWorkflowRunner>` with a
fixture-friendly constructor and helpers for common test assertions.

For most unit-test scenarios prefer :class:`FakeWorkflowBackend
<src.testkit.fake_workflow_backend.FakeWorkflowBackend>` which requires no
database at all. Use ``WorkflowRunner`` when you need to exercise the
full execution path including step processors and event persistence.

Example::

    runner = WorkflowRunner()
    result = await runner.run("credit_approval", input={"client_id": 42})
    assert result.status == "completed"
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from src.backend.core.workflow import WorkflowHandle, WorkflowResult

__all__ = ("WorkflowRunner", "WorkflowRunResult")


@dataclass(slots=True, frozen=True)
class WorkflowRunResult:
    """Result of awaiting a workflow completion via :class:`WorkflowRunner`."""

    output: dict[str, Any]
    """Workflow output payload on success."""

    status: str
    """Final status: ``completed``, ``failed``, ``cancelled``, or ``timed_out``."""

    failure: dict[str, Any] | None = None
    """Error details when ``status`` indicates a terminal failure."""


class WorkflowRunner:
    """Simplified workflow runner for unit tests.

    This is a thin facade over :class:`DurableWorkflowRunner` that
    pre-configures an in-memory event store and a
    :class:`FakeWorkflowBackend <src.testkit.fake_workflow_backend.FakeWorkflowBackend>`
    so tests can run without external infrastructure.

    For a complete walkthrough of available configuration options,
    see :class:`FakeWorkflowBackend <src.backend.core.workflow.fake_backend.FakeWorkflowBackend>`.

    Attributes:
        backend: The underlying :class:`FakeWorkflowBackend` instance used
            by this runner. Tests can inspect ``backend._instances``,
            use ``backend.set_result()``, or call ``backend.signals_for()``
            to verify workflow behavior.
    """

    def __init__(
        self,
        *,
        default_result: WorkflowResult | None = None,
        query_handlers: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Initialize the WorkflowRunner.

        Args:
            default_result: Default result returned from
                :meth:`FakeWorkflowBackend.await_completion` for workflows
                that haven't been explicitly configured via
                :meth:`FakeWorkflowBackend.set_result`.
            query_handlers: Static responses returned from
                :meth:`FakeWorkflowBackend.query_workflow` by query name.
        """
        # Lazy import to avoid pulling in heavy infrastructure dependencies
        # when only FakeWorkflowBackend is needed.
        from src.backend.core.workflow import FakeWorkflowBackend

        self.backend: FakeWorkflowBackend = FakeWorkflowBackend(
            default_result=default_result, query_handlers=query_handlers
        )

    async def run(
        self,
        workflow_name: str,
        workflow_id: str,
        input: dict[str, Any],
        *,
        namespace: str = "test",
        task_queue: str = "default",
        execution_timeout: timedelta | None = None,
    ) -> WorkflowRunResult:
        """Start a workflow and wait for completion.

        Args:
            workflow_name: Name of the workflow definition to execute.
            workflow_id: Unique identifier for this workflow instance.
            input: JSON-serializable input payload passed to the workflow.
            namespace: Tenant / namespace identifier (default ``"test"``).
            task_queue: Task queue name (default ``"default"``).
            execution_timeout: Optional wall-time limit for execution.

        Returns:
            WorkflowRunResult with output, status, and optional failure.
        """
        handle = await self.backend.start_workflow(
            workflow_name=workflow_name,
            workflow_id=workflow_id,
            input=input,
            namespace=namespace,
            task_queue=task_queue,
            execution_timeout=execution_timeout,
        )
        result = await self.backend.await_completion(
            handle=handle, timeout=execution_timeout
        )
        return WorkflowRunResult(
            output=result.output, status=result.status, failure=result.failure
        )

    async def start(
        self,
        workflow_name: str,
        workflow_id: str,
        input: dict[str, Any],
        *,
        namespace: str = "test",
        task_queue: str = "default",
        execution_timeout: timedelta | None = None,
    ) -> WorkflowHandle:
        """Start a workflow without waiting for completion.

        Returns the workflow handle for later awaiting, signaling, or querying.

        Args:
            workflow_name: Name of the workflow definition to execute.
            workflow_id: Unique identifier for this workflow instance.
            input: JSON-serializable input payload passed to the workflow.
            namespace: Tenant / namespace identifier (default ``"test"``).
            task_queue: Task queue name (default ``"default"``).
            execution_timeout: Optional wall-time limit for execution.

        Returns:
            WorkflowHandle that can be used with
            :meth:`FakeWorkflowBackend.await_completion`,
            :meth:`FakeWorkflowBackend.signal_workflow`, etc.
        """
        return await self.backend.start_workflow(
            workflow_name=workflow_name,
            workflow_id=workflow_id,
            input=input,
            namespace=namespace,
            task_queue=task_queue,
            execution_timeout=execution_timeout,
        )
