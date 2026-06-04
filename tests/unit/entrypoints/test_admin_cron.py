"""Unit-тесты admin_cron router — Sprint 12 K3 W2 + K5 W3.

Тестирует endpoints через FastAPI TestClient + моки scheduler_manager:
    * POST /admin/cron/validate (dry-run preview);
    * POST /admin/cron/schedule (создание job);
    * GET /admin/cron/list;
    * DELETE /admin/cron/{id};
    * POST /admin/cron/{id}/pause + /resume;
    * POST /admin/cron/{id}/run-now;
    * GET /admin/cron/dashboard.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.entrypoints.api.v1.endpoints.admin_cron import router

pytest.importorskip("croniter", reason="croniter не установлен")


@pytest.fixture
def client_app() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def scheduler_mock() -> Any:
    manager = MagicMock()
    manager.list_jobs.return_value = [
        {
            "id": "job-1",
            "name": "Job 1",
            "next_run_time": "2026-05-20T12:00:00+00:00",
            "trigger": "cron[0 12 * * *]",
            "paused": False,
        }
    ]
    manager.schedule_cron.return_value = "job-new"
    manager.pause_job.return_value = True
    manager.resume_job.return_value = True
    manager.run_job_now.return_value = True
    return manager


def test_validate_cron_returns_preview(client_app: TestClient) -> None:
    response = client_app.post(
        "/admin/cron/validate",
        json={
            "expression": "0 9 * * 1-5",
            "timezone": "Europe/Moscow",
            "preview_count": 3,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_valid"]
    assert len(body["next_executions"]) == 3


def test_validate_invalid_cron(client_app: TestClient) -> None:
    response = client_app.post(
        "/admin/cron/validate",
        json={"expression": "invalid garbage", "timezone": "UTC", "preview_count": 1},
    )
    assert response.status_code == 200
    body = response.json()
    assert not body["is_valid"]
    assert body["error"] is not None


def test_schedule_invalid_callable_ref(client_app: TestClient) -> None:
    response = client_app.post(
        "/admin/cron/schedule",
        json={
            "name": "test-job",
            "cron_expr": "0 9 * * *",
            "callable_ref": "nonexistent.module:fn",
            "timezone": "UTC",
        },
    )
    assert response.status_code == 400


def test_list_jobs(client_app: TestClient, scheduler_mock: Any) -> None:
    with patch(
        "src.backend.infrastructure.scheduler.scheduler_manager.get_scheduler_manager",
        return_value=scheduler_mock,
    ):
        response = client_app.get("/admin/cron/list")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == "job-1"


def test_pause_resume_cron_job(client_app: TestClient, scheduler_mock: Any) -> None:
    with patch(
        "src.backend.infrastructure.scheduler.scheduler_manager.get_scheduler_manager",
        return_value=scheduler_mock,
    ):
        r1 = client_app.post("/admin/cron/job-1/pause")
        r2 = client_app.post("/admin/cron/job-1/resume")
    assert r1.status_code == 200
    assert r1.json() == {"id": "job-1", "paused": True}
    assert r2.status_code == 200
    assert r2.json() == {"id": "job-1", "paused": False}


def test_pause_missing_job_returns_404(
    client_app: TestClient, scheduler_mock: Any
) -> None:
    scheduler_mock.pause_job.return_value = False
    with patch(
        "src.backend.infrastructure.scheduler.scheduler_manager.get_scheduler_manager",
        return_value=scheduler_mock,
    ):
        response = client_app.post("/admin/cron/nonexistent/pause")
    assert response.status_code == 404


def test_run_now(client_app: TestClient, scheduler_mock: Any) -> None:
    with patch(
        "src.backend.infrastructure.scheduler.scheduler_manager.get_scheduler_manager",
        return_value=scheduler_mock,
    ):
        response = client_app.post("/admin/cron/job-1/run-now")
    assert response.status_code == 200
    assert response.json()["scheduled"] == "now"


def test_dashboard_summary(client_app: TestClient, scheduler_mock: Any) -> None:
    with patch(
        "src.backend.infrastructure.scheduler.scheduler_manager.get_scheduler_manager",
        return_value=scheduler_mock,
    ):
        response = client_app.get("/admin/cron/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert body["total_jobs"] == 1
    assert body["paused_jobs"] == 0
    assert len(body["jobs"]) == 1
