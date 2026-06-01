"""Unit-тесты admin_workflow_versioning — Sprint 12 K3 W8."""

# ruff: noqa: S101

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.dsl.workflow.versioning import (
    WorkflowVersion,
    WorkflowVersionRegistry,
    get_global_registry,
)
from src.backend.entrypoints.api.v1.endpoints.admin_workflow_versioning import (
    router,
)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    """Сбросить global registry для test isolation."""
    registry = get_global_registry()
    registry.versions.clear()
    yield
    registry.versions.clear()


def test_history_empty_for_unknown_workflow(client: TestClient) -> None:
    response = client.get("/admin/workflow-versioning/unknown/history")
    assert response.status_code == 200
    assert response.json() == []


def test_history_lists_versions(client: TestClient) -> None:
    reg = get_global_registry()
    reg.register(WorkflowVersion(workflow_id="wf-1", major=1, minor=0))
    reg.register(
        WorkflowVersion(workflow_id="wf-1", major=1, minor=1, default_version=True)
    )

    response = client.get("/admin/workflow-versioning/wf-1/history")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["semver"].startswith("1.0")
    assert body[1]["semver"].startswith("1.1")
    assert body[1]["default_version"] is True


def test_pin_invalid_semver_returns_400(client: TestClient) -> None:
    response = client.post(
        "/admin/workflow-versioning/wf/pin", params={"semver": "not-a-version"}
    )
    assert response.status_code == 400


def test_pin_unknown_workflow_returns_404(client: TestClient) -> None:
    response = client.post(
        "/admin/workflow-versioning/wf/pin", params={"semver": "1.0"}
    )
    assert response.status_code == 404


def test_pin_changes_default(client: TestClient) -> None:
    reg = get_global_registry()
    reg.register(
        WorkflowVersion(workflow_id="wf", major=1, minor=0, default_version=True)
    )
    reg.register(WorkflowVersion(workflow_id="wf", major=1, minor=1))

    target_semver = reg.history("wf")[1].semver
    response = client.post(
        "/admin/workflow-versioning/wf/pin", params={"semver": target_semver}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["semver"] == target_semver
    assert body["default_version"] is True


def test_rollback_to_previous(client: TestClient) -> None:
    reg = get_global_registry()
    reg.register(WorkflowVersion(workflow_id="wf", major=1, minor=0))
    reg.register(
        WorkflowVersion(workflow_id="wf", major=1, minor=1, default_version=True)
    )

    previous_semver = reg.history("wf")[0].semver
    response = client.post("/admin/workflow-versioning/wf/rollback")
    assert response.status_code == 200
    body = response.json()
    assert body["rolled_back"]
    assert body["new_default"]["semver"] == previous_semver


def test_rollback_no_previous_returns_400(client: TestClient) -> None:
    reg = get_global_registry()
    reg.register(
        WorkflowVersion(workflow_id="wf-solo", major=1, minor=0, default_version=True)
    )

    response = client.post("/admin/workflow-versioning/wf-solo/rollback")
    assert response.status_code == 400


def test_running_count_returns_empty_when_temporal_unavailable(
    client: TestClient,
) -> None:
    response = client.get("/admin/workflow-versioning/wf/running-count")
    assert response.status_code == 200
    body = response.json()
    assert body["workflow_id"] == "wf"
    assert isinstance(body["counts"], dict)
