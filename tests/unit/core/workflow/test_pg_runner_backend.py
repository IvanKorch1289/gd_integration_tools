# ruff: noqa: S101
"""Unit-тесты ``PgRunnerWorkflowBackend`` через mock state/event stores.

Wave D.1 / ADR-045: проверяет контракт adapter'а без поднятия
Postgres. Реальные интеграционные тесты с testcontainers — Wave D.3.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.core.workflow import WorkflowHandle, WorkflowResult
from src.infrastructure.database.models.workflow_event import WorkflowEventType
from src.infrastructure.database.models.workflow_instance import WorkflowStatus
from src.infrastructure.workflow.pg_runner_backend import PgRunnerWorkflowBackend
from src.infrastructure.workflow.state_store import WorkflowInstanceRow


class _FakeEventStore:
    """In-memory event_store для тестов."""

    def __init__(self) -> None:
        self.appended: list[
            tuple[UUID, WorkflowEventType, dict[str, Any], str | None]
        ] = []

    async def append(
        self,
        workflow_id: UUID,
        event_type: WorkflowEventType,
        payload: dict[str, Any],
        step_name: str | None = None,
    ) -> int:
        self.appended.append((workflow_id, event_type, dict(payload), step_name))
        return len(self.appended)


class _FakeStateStore:
    """In-memory state_store для тестов."""

    def __init__(self) -> None:
        self._rows: dict[UUID, WorkflowInstanceRow] = {}
        self.create_calls: list[dict[str, Any]] = []
        self.status_updates: list[tuple[UUID, WorkflowStatus]] = []

    def _make_row(
        self,
        instance_id: UUID,
        workflow_name: str,
        route_id: str,
        input_payload: dict[str, Any],
        tenant_id: str,
        *,
        status: WorkflowStatus = WorkflowStatus.pending,
        snapshot_state: dict[str, Any] | None = None,
        finished_at: datetime | None = None,
    ) -> WorkflowInstanceRow:
        now = datetime.now(timezone.utc)
        return WorkflowInstanceRow(
            id=instance_id,
            workflow_name=workflow_name,
            route_id=route_id,
            status=status,
            current_version=1,
            last_event_seq=None,
            snapshot_state=snapshot_state,
            next_attempt_at=None,
            locked_by=None,
            locked_until=None,
            tenant_id=tenant_id,
            input_payload=input_payload,
            created_at=now,
            updated_at=now,
            finished_at=finished_at,
        )

    async def create(
        self,
        workflow_name: str,
        route_id: str,
        input_payload: dict[str, Any],
        tenant_id: str | None = None,
    ) -> UUID:
        self.create_calls.append(
            {
                "workflow_name": workflow_name,
                "route_id": route_id,
                "input_payload": dict(input_payload),
                "tenant_id": tenant_id,
            }
        )
        instance_id = uuid4()
        self._rows[instance_id] = self._make_row(
            instance_id,
            workflow_name,
            route_id,
            dict(input_payload),
            tenant_id or "default",
        )
        return instance_id

    async def get(self, workflow_id: UUID) -> WorkflowInstanceRow | None:
        return self._rows.get(workflow_id)

    async def update_status(
        self,
        workflow_id: UUID,
        status: WorkflowStatus,
        next_attempt_at: datetime | None = None,
        error: str | None = None,
    ) -> None:
        self.status_updates.append((workflow_id, status))
        existing = self._rows.get(workflow_id)
        if existing is None:
            return
        snapshot = dict(existing.snapshot_state or {})
        if error is not None:
            snapshot["last_error"] = error
        finished_at = (
            existing.finished_at
            if status
            not in {
                WorkflowStatus.succeeded,
                WorkflowStatus.failed,
                WorkflowStatus.cancelled,
            }
            else datetime.now(timezone.utc)
        )
        self._rows[workflow_id] = self._make_row(
            existing.id,
            existing.workflow_name,
            existing.route_id,
            existing.input_payload,
            existing.tenant_id,
            status=status,
            snapshot_state=snapshot or None,
            finished_at=finished_at,
        )

    # test-helpers
    def force_set(
        self,
        workflow_id: UUID,
        *,
        status: WorkflowStatus | None = None,
        snapshot_state: dict[str, Any] | None = None,
    ) -> None:
        existing = self._rows[workflow_id]
        self._rows[workflow_id] = self._make_row(
            existing.id,
            existing.workflow_name,
            existing.route_id,
            existing.input_payload,
            existing.tenant_id,
            status=status if status is not None else existing.status,
            snapshot_state=(
                snapshot_state
                if snapshot_state is not None
                else existing.snapshot_state
            ),
            finished_at=(
                datetime.now(timezone.utc)
                if status
                in {
                    WorkflowStatus.succeeded,
                    WorkflowStatus.failed,
                    WorkflowStatus.cancelled,
                }
                else existing.finished_at
            ),
        )


@pytest.fixture
def stores() -> tuple[_FakeStateStore, _FakeEventStore]:
    return _FakeStateStore(), _FakeEventStore()


@pytest.fixture
def backend(stores: tuple[_FakeStateStore, _FakeEventStore]) -> PgRunnerWorkflowBackend:
    state, events = stores
    return PgRunnerWorkflowBackend(
        state_store=state,
        event_store=events,
        poll_interval_s=0.01,
        poll_max_interval_s=0.05,
    )


@pytest.mark.asyncio
class TestStartWorkflow:
    async def test_creates_instance_with_metadata(
        self,
        backend: PgRunnerWorkflowBackend,
        stores: tuple[_FakeStateStore, _FakeEventStore],
    ) -> None:
        state, _ = stores
        handle = await backend.start_workflow(
            workflow_name="orders.skb_flow",
            workflow_id="user-supplied-tag",
            input={"client_id": 42},
            namespace="bank-a",
            task_queue="default",
            execution_timeout=timedelta(minutes=10),
        )
        assert handle.workflow_id == "user-supplied-tag"
        assert handle.namespace == "bank-a"
        assert UUID(hex=handle.run_id)  # валидный UUID
        assert len(state.create_calls) == 1
        call = state.create_calls[0]
        assert call["workflow_name"] == "orders.skb_flow"
        assert call["tenant_id"] == "bank-a"
        assert call["input_payload"]["__workflow_id"] == "user-supplied-tag"
        assert call["input_payload"]["__task_queue"] == "default"
        assert call["input_payload"]["__execution_timeout_s"] == 600.0
        assert call["input_payload"]["client_id"] == 42

    async def test_global_namespace_maps_to_default_tenant(
        self,
        backend: PgRunnerWorkflowBackend,
        stores: tuple[_FakeStateStore, _FakeEventStore],
    ) -> None:
        state, _ = stores
        await backend.start_workflow(
            workflow_name="wf",
            workflow_id="wf-1",
            input={},
            namespace="global",
            task_queue="q",
        )
        assert state.create_calls[0]["tenant_id"] == "default"


@pytest.mark.asyncio
class TestSignalWorkflow:
    async def test_appends_signal_received_event(
        self,
        backend: PgRunnerWorkflowBackend,
        stores: tuple[_FakeStateStore, _FakeEventStore],
    ) -> None:
        _, events = stores
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
        assert len(events.appended) == 1
        instance_id, event_type, payload, step_name = events.appended[0]
        assert instance_id.hex == handle.run_id
        assert event_type is WorkflowEventType.signal_received
        assert payload == {"signal_name": "approve", "data": {"by": "ops"}}
        assert step_name is None

    async def test_invalid_run_id_raises(
        self, backend: PgRunnerWorkflowBackend
    ) -> None:
        bad = WorkflowHandle(workflow_id="x", run_id="not-a-uuid", namespace="t")
        with pytest.raises(ValueError):
            await backend.signal_workflow(handle=bad, signal_name="s", payload={})


@pytest.mark.asyncio
class TestQueryWorkflow:
    async def test_dollar_state_returns_full_snapshot(
        self,
        backend: PgRunnerWorkflowBackend,
        stores: tuple[_FakeStateStore, _FakeEventStore],
    ) -> None:
        state, _ = stores
        handle = await backend.start_workflow(
            workflow_name="wf",
            workflow_id="wf-1",
            input={},
            namespace="t",
            task_queue="q",
        )
        instance_id = UUID(hex=handle.run_id)
        state.force_set(instance_id, snapshot_state={"phase": "review", "score": 0.8})
        snapshot = await backend.query_workflow(handle=handle, query_name="$state")
        assert snapshot == {"phase": "review", "score": 0.8}

    async def test_named_query_returns_subdict(
        self,
        backend: PgRunnerWorkflowBackend,
        stores: tuple[_FakeStateStore, _FakeEventStore],
    ) -> None:
        state, _ = stores
        handle = await backend.start_workflow(
            workflow_name="wf",
            workflow_id="wf-1",
            input={},
            namespace="t",
            task_queue="q",
        )
        instance_id = UUID(hex=handle.run_id)
        state.force_set(instance_id, snapshot_state={"meta": {"v": 1}})
        result = await backend.query_workflow(handle=handle, query_name="meta")
        assert result == {"v": 1}

    async def test_named_scalar_wrapped_in_value(
        self,
        backend: PgRunnerWorkflowBackend,
        stores: tuple[_FakeStateStore, _FakeEventStore],
    ) -> None:
        state, _ = stores
        handle = await backend.start_workflow(
            workflow_name="wf",
            workflow_id="wf-1",
            input={},
            namespace="t",
            task_queue="q",
        )
        instance_id = UUID(hex=handle.run_id)
        state.force_set(instance_id, snapshot_state={"score": 0.91})
        result = await backend.query_workflow(handle=handle, query_name="score")
        assert result == {"value": 0.91}

    async def test_unknown_handle_raises(
        self, backend: PgRunnerWorkflowBackend
    ) -> None:
        ghost = WorkflowHandle(workflow_id="x", run_id=uuid4().hex, namespace="t")
        with pytest.raises(KeyError):
            await backend.query_workflow(handle=ghost, query_name="$state")


@pytest.mark.asyncio
class TestCancelWorkflow:
    async def test_status_set_to_cancelling(
        self,
        backend: PgRunnerWorkflowBackend,
        stores: tuple[_FakeStateStore, _FakeEventStore],
    ) -> None:
        state, _ = stores
        handle = await backend.start_workflow(
            workflow_name="wf",
            workflow_id="wf-1",
            input={},
            namespace="t",
            task_queue="q",
        )
        await backend.cancel_workflow(handle=handle)
        instance_id = UUID(hex=handle.run_id)
        assert (instance_id, WorkflowStatus.cancelling) in state.status_updates


@pytest.mark.asyncio
class TestAwaitCompletion:
    async def test_succeeded_returns_completed(
        self,
        backend: PgRunnerWorkflowBackend,
        stores: tuple[_FakeStateStore, _FakeEventStore],
    ) -> None:
        state, _ = stores
        handle = await backend.start_workflow(
            workflow_name="wf",
            workflow_id="wf-1",
            input={},
            namespace="t",
            task_queue="q",
        )
        instance_id = UUID(hex=handle.run_id)
        state.force_set(
            instance_id,
            status=WorkflowStatus.succeeded,
            snapshot_state={"result": "ok"},
        )
        result = await backend.await_completion(handle=handle)
        assert isinstance(result, WorkflowResult)
        assert result.status == "completed"
        assert result.output == {"result": "ok"}
        assert result.failure is None

    async def test_failed_with_last_error(
        self,
        backend: PgRunnerWorkflowBackend,
        stores: tuple[_FakeStateStore, _FakeEventStore],
    ) -> None:
        state, _ = stores
        handle = await backend.start_workflow(
            workflow_name="wf",
            workflow_id="wf-1",
            input={},
            namespace="t",
            task_queue="q",
        )
        instance_id = UUID(hex=handle.run_id)
        state.force_set(
            instance_id,
            status=WorkflowStatus.failed,
            snapshot_state={"last_error": "boom", "step": 2},
        )
        result = await backend.await_completion(handle=handle)
        assert result.status == "failed"
        assert result.output == {"step": 2}
        assert result.failure is not None
        assert result.failure["message"] == "boom"

    async def test_timeout_returns_timed_out(
        self,
        backend: PgRunnerWorkflowBackend,
        stores: tuple[_FakeStateStore, _FakeEventStore],
    ) -> None:
        # Не выставляем terminal-статус — должен вернуться timed_out
        handle = await backend.start_workflow(
            workflow_name="wf",
            workflow_id="wf-1",
            input={},
            namespace="t",
            task_queue="q",
        )
        result = await backend.await_completion(
            handle=handle, timeout=timedelta(milliseconds=20)
        )
        assert result.status == "timed_out"
        assert result.failure is not None
        assert "TimeoutError" == result.failure["type"]


@pytest.mark.asyncio
class TestReplay:
    async def test_replay_is_noop(self, backend: PgRunnerWorkflowBackend) -> None:
        await backend.replay(workflow_name="wf", history=b"any-bytes")
