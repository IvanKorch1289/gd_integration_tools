"""Unit tests for watcher_routes REST API (file watcher management)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.entrypoints.filewatcher import watcher_routes as mod
from src.backend.entrypoints.filewatcher.watcher_manager import WatcherSpec


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(mod.watcher_router, prefix="/api/v1")
    return app


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Returns a temporary directory for tests."""
    return tmp_path


# ─── create_watcher ──────────────────────────────────────────────────────────


def test_create_watcher_success(temp_dir: Path) -> None:
    """POST / creates a watcher and returns its spec."""
    app = _make_app()
    spec = WatcherSpec(directory=str(temp_dir), pattern="*.csv", route_id="r1", poll_interval=2.0)

    with patch.object(mod.watcher_manager, "add", return_value=spec):
        client = TestClient(app)
        resp = client.post(
            "/api/v1/watchers/",
            json={
                "directory": str(temp_dir),
                "pattern": "*.csv",
                "route_id": "r1",
                "poll_interval": 2.0,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["directory"] == str(temp_dir)
    assert data["pattern"] == "*.csv"
    assert data["route_id"] == "r1"
    assert data["poll_interval"] == 2.0
    assert "id" in data


def test_create_watcher_bad_directory() -> None:
    """POST / returns 400 when directory does not exist."""
    app = _make_app()

    with patch.object(
        mod.watcher_manager, "add", side_effect=ValueError("Директория не найдена: /nope")
    ):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/watchers/",
            json={
                "directory": "/nope",
                "pattern": "*",
                "route_id": "r1",
            },
        )

    assert resp.status_code == 400
    assert "Директория не найдена" in resp.json()["detail"]


# ─── delete_watcher ──────────────────────────────────────────────────────────


def test_delete_watcher_success() -> None:
    """DELETE /{watcher_id} removes watcher and returns status."""
    app = _make_app()

    with patch.object(mod.watcher_manager, "remove", return_value=None):
        client = TestClient(app)
        resp = client.delete("/api/v1/watchers/w-123")

    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    assert resp.json()["id"] == "w-123"


def test_delete_watcher_not_found() -> None:
    """DELETE /{watcher_id} returns 404 when watcher missing."""
    app = _make_app()

    with patch.object(
        mod.watcher_manager, "remove", side_effect=KeyError("Watcher w-123 не найден")
    ):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.delete("/api/v1/watchers/w-123")

    assert resp.status_code == 404
    assert "не найден" in resp.json()["detail"]


# ─── list_watchers ───────────────────────────────────────────────────────────


def test_list_watchers() -> None:
    """GET / returns list of watchers."""
    app = _make_app()

    mock_watchers = [
        {
            "id": "w1",
            "directory": "/tmp",
            "pattern": "*.csv",
            "route_id": "r1",
            "poll_interval": 5.0,
            "active": True,
        }
    ]

    with patch.object(
        mod.watcher_manager, "list_watchers", return_value=mock_watchers
    ):
        client = TestClient(app)
        resp = client.get("/api/v1/watchers/")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "w1"


def test_list_watchers_empty() -> None:
    """GET / returns empty list when no watchers."""
    app = _make_app()

    with patch.object(mod.watcher_manager, "list_watchers", return_value=[]):
        client = TestClient(app)
        resp = client.get("/api/v1/watchers/")

    assert resp.status_code == 200
    assert resp.json() == []


# ─── model validation ────────────────────────────────────────────────────────


def test_create_watcher_request_defaults() -> None:
    """CreateWatcherRequest has sensible defaults."""
    req = mod.CreateWatcherRequest(directory="/tmp", route_id="r1")
    assert req.pattern == "*"
    assert req.poll_interval == 5.0


def test_create_watcher_request_validation() -> None:
    """CreateWatcherRequest validates poll_interval minimum."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        mod.CreateWatcherRequest(directory="/tmp", route_id="r1", poll_interval=0.5)
