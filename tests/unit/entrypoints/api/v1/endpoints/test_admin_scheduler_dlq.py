"""Unit tests for admin_scheduler_dlq endpoints (Sprint 21 W4, G-09)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from src.backend.entrypoints.api.v1.endpoints import admin_scheduler_dlq as mod
from src.backend.infrastructure.scheduler.dlq import (
    SchedulerDLQEntry,
    SchedulerDLQStore,
)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(mod.router, prefix="/api/v1")

    @app.middleware("http")
    async def _add_auth_context(request, call_next):
        from src.backend.core.auth import AuthContext, AuthMethod

        request.state.auth_context = AuthContext(
            method=AuthMethod.NONE,
            principal="test",
            metadata={"admin_roles": ["super_admin"]},
        )
        return await call_next(request)

    return app


@pytest.fixture
def sample_entry() -> SchedulerDLQEntry:
    """Returns a sample DLQ entry."""
    return SchedulerDLQEntry(
        job_id="job-1",
        exception="ValueError: boom",
        traceback_text="trace",
        scheduled_at=datetime.now(timezone.utc),
        failed_at=datetime.now(timezone.utc),
    )


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    """Reset DLQ store singleton before each test."""
    from src.backend.infrastructure.scheduler.dlq import set_scheduler_dlq_store

    set_scheduler_dlq_store(None)
    yield
    set_scheduler_dlq_store(None)


# ─── _require_store ──────────────────────────────────────────────────────────


def test_require_store_returns_store_when_initialized(
    sample_entry: SchedulerDLQEntry,
) -> None:
    """_require_store returns store when singleton is set."""
    store = SchedulerDLQStore()
    store.add(sample_entry)
    from src.backend.infrastructure.scheduler.dlq import set_scheduler_dlq_store

    set_scheduler_dlq_store(store)
    result = mod._require_store()
    assert result is store


def test_require_store_raises_503_when_none() -> None:
    """_require_store raises 503 when store is None."""
    with pytest.raises(HTTPException) as exc_info:
        mod._require_store()
    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert "не инициализирован" in exc_info.value.detail


# ─── list_failed_jobs ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_failed_jobs(sample_entry: SchedulerDLQEntry) -> None:
    """list_failed_jobs returns serialized entries."""
    store = SchedulerDLQStore()
    store.add(sample_entry)
    from src.backend.infrastructure.scheduler.dlq import set_scheduler_dlq_store

    set_scheduler_dlq_store(store)
    result = await mod.list_failed_jobs(limit=10)
    assert len(result) == 1
    assert result[0]["job_id"] == "job-1"


# ─── get_failed_job ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_failed_job_found(sample_entry: SchedulerDLQEntry) -> None:
    """get_failed_job returns entry dict when found."""
    store = SchedulerDLQStore()
    store.add(sample_entry)
    from src.backend.infrastructure.scheduler.dlq import set_scheduler_dlq_store

    set_scheduler_dlq_store(store)
    result = await mod.get_failed_job(sample_entry.id)
    assert result["job_id"] == "job-1"


@pytest.mark.asyncio
async def test_get_failed_job_not_found() -> None:
    """get_failed_job raises 404 when entry missing."""
    store = SchedulerDLQStore()
    from src.backend.infrastructure.scheduler.dlq import set_scheduler_dlq_store

    set_scheduler_dlq_store(store)
    with pytest.raises(HTTPException) as exc_info:
        await mod.get_failed_job("non-existent")
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


# ─── retry_failed_job ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retry_failed_job_increments_retry(
    sample_entry: SchedulerDLQEntry,
) -> None:
    """retry_failed_job increments retry_count and returns entry."""
    store = SchedulerDLQStore()
    store.add(sample_entry)
    from src.backend.infrastructure.scheduler.dlq import set_scheduler_dlq_store

    set_scheduler_dlq_store(store)
    result = await mod.retry_failed_job(sample_entry.id)
    assert result["retry_count"] == 1
    assert result["reschedule_attempted"] is False


@pytest.mark.asyncio
async def test_retry_failed_job_with_scheduler(sample_entry: SchedulerDLQEntry) -> None:
    """retry_failed_job attempts reschedule when scheduler available."""
    store = SchedulerDLQStore()
    store.add(sample_entry)
    from src.backend.infrastructure.scheduler.dlq import set_scheduler_dlq_store

    set_scheduler_dlq_store(store)

    mock_scheduler = MagicMock()
    mock_scheduler.get_job.return_value = MagicMock()
    mock_manager = MagicMock()
    mock_manager.scheduler = mock_scheduler

    with patch(
        "src.backend.infrastructure.scheduler.scheduler_manager.get_scheduler_manager",
        return_value=mock_manager,
    ):
        result = await mod.retry_failed_job(sample_entry.id)

    assert result["reschedule_attempted"] is True
    mock_scheduler.reschedule_job.assert_called_once_with("job-1")


@pytest.mark.asyncio
async def test_retry_failed_job_not_found() -> None:
    """retry_failed_job raises 404 when entry missing."""
    store = SchedulerDLQStore()
    from src.backend.infrastructure.scheduler.dlq import set_scheduler_dlq_store

    set_scheduler_dlq_store(store)
    with pytest.raises(HTTPException) as exc_info:
        await mod.retry_failed_job("missing")
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


# ─── delete_failed_job ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_failed_job(sample_entry: SchedulerDLQEntry) -> None:
    """delete_failed_job removes entry and returns None."""
    store = SchedulerDLQStore()
    store.add(sample_entry)
    from src.backend.infrastructure.scheduler.dlq import set_scheduler_dlq_store

    set_scheduler_dlq_store(store)
    result = await mod.delete_failed_job(sample_entry.id)
    assert result is None
    assert store.get(sample_entry.id) is None


@pytest.mark.asyncio
async def test_delete_failed_job_not_found() -> None:
    """delete_failed_job raises 404 when entry missing."""
    store = SchedulerDLQStore()
    from src.backend.infrastructure.scheduler.dlq import set_scheduler_dlq_store

    set_scheduler_dlq_store(store)
    with pytest.raises(HTTPException) as exc_info:
        await mod.delete_failed_job("missing")
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


# ─── HTTP integration ────────────────────────────────────────────────────────


def test_list_failed_jobs_http_200(sample_entry: SchedulerDLQEntry) -> None:
    """HTTP GET returns 200 with failed jobs."""
    app = _make_app()
    store = SchedulerDLQStore()
    store.add(sample_entry)
    from src.backend.infrastructure.scheduler.dlq import set_scheduler_dlq_store

    set_scheduler_dlq_store(store)

    client = TestClient(app)
    resp = client.get("/api/v1/admin/scheduler/dlq")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["job_id"] == "job-1"


def test_get_failed_job_http_200(sample_entry: SchedulerDLQEntry) -> None:
    """HTTP GET /{entry_id} returns 200 with entry."""
    app = _make_app()
    store = SchedulerDLQStore()
    store.add(sample_entry)
    from src.backend.infrastructure.scheduler.dlq import set_scheduler_dlq_store

    set_scheduler_dlq_store(store)

    client = TestClient(app)
    resp = client.get(f"/api/v1/admin/scheduler/dlq/{sample_entry.id}")

    assert resp.status_code == 200
    assert resp.json()["job_id"] == "job-1"


def test_get_failed_job_http_404() -> None:
    """HTTP GET /{entry_id} returns 404 when missing."""
    app = _make_app()
    store = SchedulerDLQStore()
    from src.backend.infrastructure.scheduler.dlq import set_scheduler_dlq_store

    set_scheduler_dlq_store(store)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/admin/scheduler/dlq/missing")

    assert resp.status_code == 404


def test_retry_failed_job_http_200(sample_entry: SchedulerDLQEntry) -> None:
    """HTTP POST /{entry_id}/retry returns 200 with updated entry."""
    app = _make_app()
    store = SchedulerDLQStore()
    store.add(sample_entry)
    from src.backend.infrastructure.scheduler.dlq import set_scheduler_dlq_store

    set_scheduler_dlq_store(store)

    client = TestClient(app)
    resp = client.post(f"/api/v1/admin/scheduler/dlq/{sample_entry.id}/retry")

    assert resp.status_code == 200
    assert resp.json()["retry_count"] == 1


def test_delete_failed_job_http_204(sample_entry: SchedulerDLQEntry) -> None:
    """HTTP DELETE /{entry_id} returns 204."""
    app = _make_app()
    store = SchedulerDLQStore()
    store.add(sample_entry)
    from src.backend.infrastructure.scheduler.dlq import set_scheduler_dlq_store

    set_scheduler_dlq_store(store)

    client = TestClient(app)
    resp = client.delete(f"/api/v1/admin/scheduler/dlq/{sample_entry.id}")

    assert resp.status_code == 204


def test_delete_failed_job_http_404() -> None:
    """HTTP DELETE /{entry_id} returns 404 when missing."""
    app = _make_app()
    store = SchedulerDLQStore()
    from src.backend.infrastructure.scheduler.dlq import set_scheduler_dlq_store

    set_scheduler_dlq_store(store)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.delete("/api/v1/admin/scheduler/dlq/missing")

    assert resp.status_code == 404
