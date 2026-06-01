"""Public testkit API for plugin authors (K5 S19 W3, S-L10-1).

This package provides a stable public API for writing tests against
GD Integration Tools plugins and extensions. It re-exports the most
commonly used test doubles, fixtures, and assertion helpers from the
internal testkit implementation.

Example usage in a plugin test::

    import pytest
    from src.testkit import (
        RouteRunner,
        FakeWorkflowBackend,
        MockCapabilityGateway,
        assert_audit_event,
        assert_metric_recorded,
    )

    @pytest.mark.asyncio
    async def test_my_plugin_route():
        runner = RouteRunner()
        result = await runner.run("my_plugin.health", {"ping": True})
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_my_workflow():
        backend = FakeWorkflowBackend()
        # ... setup and run workflow tests

Public API summary:

* **RouteRunner** — isolated DSL-route execution without a live ASGI app.
* **WorkflowRunner** — thin wrapper over DurableWorkflowRunner for tests.
* **FakeWorkflowBackend** — in-memory WorkflowBackend implementation.
* **MockCapabilityGateway** — configurable mock for CapabilityGatewayProtocol.
* **recorder fixtures** — ``har_recorder``, ``har_cassette_path`` via
  :func:`record` and :func:`replay` helpers.
* **assert_audit_event** — assertion helper to verify audit events.
* **assert_metric_recorded** — assertion helper to verify metrics were recorded.
"""

from __future__ import annotations

from src.testkit.assertions import (
    assert_audit_event,
    assert_metric_recorded,
)
from src.testkit.fake_workflow_backend import FakeWorkflowBackend
from src.testkit.mock_capability_gateway import MockCapabilityGateway
from src.testkit.recorder import (
    HARCassette,
    HAREntry,
    HARRecorder,
    build_replay_transport,
    cassette,
    load_cassette,
    record_session,
    save_cassette,
)
from src.testkit.route_runner import RouteRunner, RouteRunResult
from src.testkit.workflow_runner import WorkflowRunner, WorkflowRunResult

__all__ = (
    # RouteRunner
    "RouteRunner",
    "RouteRunResult",
    # WorkflowRunner
    "WorkflowRunner",
    "WorkflowRunResult",
    # WorkflowBackend
    "FakeWorkflowBackend",
    # CapabilityGateway
    "MockCapabilityGateway",
    # Recorder/replay
    "HARCassette",
    "HAREntry",
    "HARRecorder",
    "build_replay_transport",
    "cassette",
    "load_cassette",
    "record_session",
    "save_cassette",
    # Assertions
    "assert_audit_event",
    "assert_metric_recorded",
)

__version__ = "1.0.0"
