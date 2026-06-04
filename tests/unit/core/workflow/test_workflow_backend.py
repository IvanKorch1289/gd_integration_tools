"""Unit tests for WorkflowBackend Protocol and FakeWorkflowBackend."""

# ruff: noqa: S101

from __future__ import annotations

from datetime import timedelta

import pytest

from src.backend.core.workflow import (
    FakeWorkflowBackend,
    WorkflowBackend,
    WorkflowHandle,
    WorkflowResult,
    WorkflowStatus,
)
from src.backend.core.workflow.backend import WorkflowBackend as WBProtocol


# ─── Protocol conformance ───────────────────────────────────────────────────


def test_fake_workflow_backend_is_instance() -> None:
    backend = FakeWorkflowBackend()
    assert isinstance(backend, WBProtocol)


# ─── FakeWorkflowBackend ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_workflow_returns_handle() -> None:
    backend = FakeWorkflowBackend()
    handle = await backend.start_workflow(
        workflow_name="wf1",
        workflow_id="id1",
        input={"x": 1},
        namespace="ns1",
        task_queue="tq",
    )
    assert isinstance(handle, WorkflowHandle)
    assert handle.workflow_id == "id1"
    assert handle.namespace == "ns1"
    assert handle.run_id


@pytest.mark.asyncio
async def test_signal_workflow_records() -> None:
    backend = FakeWorkflowBackend()
    handle = await backend.start_workflow(
        workflow_name="wf1",
        workflow_id="id1",
        input={},
        namespace="ns",
        task_queue="tq",
    )
    await backend.signal_workflow(handle=handle, signal_name="s1", payload={"a": 1})
    assert backend.signals_for(handle) == [("s1", {"a": 1})]


@pytest.mark.asyncio
async def test_query_workflow_static() -> None:
    backend = FakeWorkflowBackend(query_handlers={"q1": {"answer": 42}})
    handle = await backend.start_workflow(
        workflow_name="wf1",
        workflow_id="id1",
        input={},
        namespace="ns",
        task_queue="tq",
    )
    result = await backend.query_workflow(handle=handle, query_name="q1")
    assert result == {"answer": 42}


@pytest.mark.asyncio
async def test_query_workflow_missing_returns_empty() -> None:
    backend = FakeWorkflowBackend()
    handle = await backend.start_workflow(
        workflow_name="wf1",
        workflow_id="id1",
        input={},
        namespace="ns",
        task_queue="tq",
    )
    result = await backend.query_workflow(handle=handle, query_name="unknown")
    assert result == {}


@pytest.mark.asyncio
async def test_cancel_workflow() -> None:
    backend = FakeWorkflowBackend()
    handle = await backend.start_workflow(
        workflow_name="wf1",
        workflow_id="id1",
        input={},
        namespace="ns",
        task_queue="tq",
    )
    await backend.cancel_workflow(handle=handle)
    assert backend.is_cancelled(handle) is True
    result = await backend.await_completion(handle=handle)
    assert result.status == "cancelled"


@pytest.mark.asyncio
async def test_await_completion_default() -> None:
    backend = FakeWorkflowBackend()
    handle = await backend.start_workflow(
        workflow_name="wf1",
        workflow_id="id1",
        input={},
        namespace="ns",
        task_queue="tq",
    )
    result = await backend.await_completion(handle=handle)
    assert result.status == "completed"
    assert result.output == {}


@pytest.mark.asyncio
async def test_await_completion_custom_default() -> None:
    backend = FakeWorkflowBackend(
        default_result=WorkflowResult(status="failed", failure={"msg": "oops"})
    )
    handle = await backend.start_workflow(
        workflow_name="wf1",
        workflow_id="id1",
        input={},
        namespace="ns",
        task_queue="tq",
    )
    result = await backend.await_completion(handle=handle)
    assert result.status == "failed"
    assert result.failure == {"msg": "oops"}


@pytest.mark.asyncio
async def test_set_result_overrides() -> None:
    backend = FakeWorkflowBackend()
    handle = await backend.start_workflow(
        workflow_name="wf1",
        workflow_id="id1",
        input={},
        namespace="ns",
        task_queue="tq",
    )
    backend.set_result(handle, WorkflowResult(status="completed", output={"x": 1}))
    result = await backend.await_completion(handle=handle)
    assert result.output == {"x": 1}


@pytest.mark.asyncio
async def test_replay_noop() -> None:
    backend = FakeWorkflowBackend()
    await backend.replay(workflow_name="wf1", history=b"hist")


@pytest.mark.asyncio
async def test_require_raises_on_bad_handle() -> None:
    backend = FakeWorkflowBackend()
    bad_handle = WorkflowHandle(workflow_id="x", run_id="y", namespace="z")
    with pytest.raises(KeyError, match="Unknown fake workflow"):
        await backend.await_completion(handle=bad_handle)


@pytest.mark.asyncio
async def test_require_raises_on_mismatched_handle() -> None:
    backend = FakeWorkflowBackend()
    handle = await backend.start_workflow(
        workflow_name="wf1",
        workflow_id="id1",
        input={},
        namespace="ns",
        task_queue="tq",
    )
    bad_handle = WorkflowHandle(workflow_id="x", run_id=handle.run_id, namespace="z")
    with pytest.raises(ValueError, match="Handle mismatch"):
        await backend.await_completion(handle=bad_handle)


# ─── WorkflowResult / WorkflowHandle models ─────────────────────────────────


def test_workflow_handle_frozen() -> None:
    h = WorkflowHandle(workflow_id="a", run_id="b", namespace="c")
    with pytest.raises(Exception):
        h.workflow_id = "d"


def test_workflow_result_defaults() -> None:
    r = WorkflowResult(status="completed")
    assert r.output == {}
    assert r.failure is None
