"""K5 S19 W3: src/testkit/ public API для extensions/plugin authors.

Этот пакет предоставляет public API для написания тестов extensions и
plugin authors. Активируется флагом ``testkit_public_api``.

Публичный API:
    * :class:`RouteRunner` — изолированный запуск DSL-route.
    * :class:`WorkflowRunner` — запуск workflow в тестах.
    * :class:`MockCapabilityGateway` — mock :class:`CapabilityGatewayProtocol`.
    * :class:`FakeWorkflowBackend` — in-memory :class:`WorkflowBackend`.
    * HAR recorder/replay fixtures (:mod:`testkit.recorder`, :mod:`testkit.replay`).
    * :func:`assert_audit_event` — assertion helper для audit events.
    * :func:`assert_metric_recorded` — assertion helper для metrics.

См. ``docs/testkit/`` для документации.
"""

from __future__ import annotations

# Re-export all public components
from src.testkit.fake_workflow_backend import FakeWorkflowBackend
from src.testkit.mock_capability_gateway import MockCapabilityGateway
from src.testkit.route_runner import RouteRunResult, RouteRunner
from src.testkit.workflow_runner import WorkflowRunResult, WorkflowRunner
from src.testkit.assertions import assert_audit_event, assert_metric_recorded

# Recorder/replay re-exports (from root testkit package)
from testkit.recorder import (
    HARCassette,
    HAREntry,
    HARRecorder,
    cassette,
    load_cassette,
    record_session,
)
from testkit.replay import (
    MissingCassetteEntry,
    build_replay_transport,
    load_cassette as load_replay_cassette,
)

__all__: tuple[str, ...] = (
    # RouteRunner
    "RouteRunResult",
    "RouteRunner",
    # WorkflowRunner
    "WorkflowRunResult",
    "WorkflowRunner",
    # Mock / Fake
    "MockCapabilityGateway",
    "FakeWorkflowBackend",
    # Assertions
    "assert_audit_event",
    "assert_metric_recorded",
    # HAR recorder/replay
    "HARCassette",
    "HAREntry",
    "HARRecorder",
    "MissingCassetteEntry",
    "build_replay_transport",
    "cassette",
    "load_cassette",
    "record_session",
)
