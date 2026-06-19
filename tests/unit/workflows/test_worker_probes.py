"""Unit-тесты для WorkerProbesServer."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import CollectorRegistry
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from src.backend.infrastructure.observability.metrics_registry import MetricsRegistry
from src.backend.infrastructure.workflow import worker_probes as wp  # S168 W13: moved from src/backend/workflows/


@pytest.fixture(autouse=True)
def _isolate_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    """Изолирует Prometheus-метрики для каждого теста."""
    temp_registry = CollectorRegistry()
    temp_metrics = MetricsRegistry(default_labels=(), registry=temp_registry)

    monkeypatch.setattr(
        wp,
        "WORKER_UP",
        temp_metrics.gauge("workflow_worker_up", "Worker up.", labels=("worker_id",)),
    )
    monkeypatch.setattr(
        wp,
        "WORKER_QUEUE_DEPTH",
        temp_metrics.gauge(
            "workflow_worker_queue_depth", "Queue depth.", labels=("worker_id",)
        ),
    )
    monkeypatch.setattr(
        wp,
        "WORKER_ACTIVE_EXECUTIONS",
        temp_metrics.gauge(
            "workflow_worker_active_executions",
            "Active executions.",
            labels=("worker_id",),
        ),
    )
    monkeypatch.setattr(wp, "REGISTRY", temp_registry)
    monkeypatch.setattr(wp.metrics_registry, "_registry", temp_registry)


def _make_client(
    *,
    runner: Any | None = None,
    worker_id: str = "test-worker",
    readiness_check: Any | None = None,
    draining: bool = False,
) -> tuple[TestClient, wp.WorkerProbesServer]:
    """Создаёт TestClient над WorkerProbesServer без запуска uvicorn."""
    server = wp.WorkerProbesServer(
        runner=runner or MagicMock(),
        worker_id=worker_id,
        port=0,
        readiness_check=readiness_check,
    )
    if draining:
        server.mark_draining()

    app = Starlette(
        routes=[
            Route("/healthz", server._handle_healthz),
            Route("/readyz", server._handle_readyz),
            Route("/metrics", server._handle_metrics),
        ]
    )
    return TestClient(app), server


@pytest.mark.unit
def test_healthz_ok() -> None:
    client, _ = _make_client()
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.unit
def test_healthz_draining() -> None:
    client, _ = _make_client(draining=True)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "draining"}


@pytest.mark.unit
def test_readyz_ready() -> None:
    runner = MagicMock()
    runner._running = True
    client, _ = _make_client(
        runner=runner, readiness_check=AsyncMock(return_value=True)
    )
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.unit
def test_readyz_not_ready_runner() -> None:
    runner = MagicMock()
    runner._running = False
    client, _ = _make_client(runner=runner)
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["reason"] == "runner_not_started"


@pytest.mark.unit
def test_readyz_not_ready_check() -> None:
    runner = MagicMock()
    runner._running = True
    client, _ = _make_client(
        runner=runner, readiness_check=AsyncMock(return_value=False)
    )
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["reason"] == "dependency_unhealthy"


@pytest.mark.unit
def test_readyz_draining() -> None:
    runner = MagicMock()
    runner._running = True
    client, _ = _make_client(
        runner=runner, readiness_check=AsyncMock(return_value=True), draining=True
    )
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["reason"] == "draining"


@pytest.mark.unit
def test_readyz_check_error() -> None:
    runner = MagicMock()
    runner._running = True
    client, _ = _make_client(
        runner=runner, readiness_check=AsyncMock(side_effect=RuntimeError("boom"))
    )
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert "boom" in response.json()["reason"]


@pytest.mark.unit
def test_metrics_content() -> None:
    queue = asyncio.Queue()
    queue.put_nowait("wf-1")
    queue.put_nowait("wf-2")

    runner = MagicMock()
    runner._active_executions = {"a", "b"}
    runner._pending_instance_ids = queue

    client, _ = _make_client(runner=runner, worker_id="w-42")
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.text

    assert "workflow_worker_up" in body
    assert "workflow_worker_queue_depth" in body
    assert "workflow_worker_active_executions" in body
    assert 'worker_id="w-42"' in body


@pytest.mark.unit
def test_start_sets_worker_up_and_creates_task(monkeypatch: pytest.MonkeyPatch) -> None:
    server = wp.WorkerProbesServer(runner=MagicMock(), worker_id="w-1", port=9999)

    mock_task = MagicMock()
    mock_task.done.return_value = True
    mock_registry = MagicMock()
    mock_registry.create_task.return_value = mock_task

    monkeypatch.setattr(wp, "get_task_registry", lambda: mock_registry)

    asyncio.run(server.start())

    mock_registry.create_task.assert_called_once()
    assert server._server is not None
    sample = wp.WORKER_UP.labels(worker_id="w-1")._samples()[0]
    assert sample.value == 1.0


@pytest.mark.unit
def test_stop_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    server = wp.WorkerProbesServer(runner=MagicMock(), worker_id="w-1", port=9999)

    mock_task = MagicMock()
    mock_task.done.return_value = True
    mock_registry = MagicMock()
    mock_registry.create_task.return_value = mock_task

    monkeypatch.setattr(wp, "get_task_registry", lambda: mock_registry)

    asyncio.run(server.start())
    asyncio.run(server.stop())

    assert server._draining is True
    sample = wp.WORKER_UP.labels(worker_id="w-1")._samples()[0]
    assert sample.value == 0.0
