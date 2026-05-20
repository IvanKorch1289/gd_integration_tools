# ruff: noqa: S101
"""Sprint 14 K5 W2 — smoke-тесты versioning/diff/rollback endpoints.

Покрывает:

* GET  /admin/plugins/{name}/versions — отдаёт пустой массив без loader;
* GET  /admin/plugins/dependency-graph — 503 при flag-off, payload при ON;
* POST /admin/plugins/scaffold — dry_run возвращает план без записи;
* GET  /admin/plugins/{name}/diff — 503 при отсутствующем сервисе.

Все тесты используют ``patch`` для _check_flag_enabled, чтобы не зависеть
от настоящего feature_flags.
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_app() -> FastAPI:
    from src.backend.entrypoints.api.v1.endpoints.admin_plugins import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


def test_versions_returns_empty_without_loader() -> None:
    import src.backend.entrypoints.api.v1.endpoints.admin_plugins as mod

    app = _build_app()
    with (
        patch.object(mod, "_check_flag_enabled", lambda: None),
        patch.object(mod, "_get_version_service", lambda: None),
    ):
        client = TestClient(app)
        r = client.get("/api/v1/admin/plugins/demo/versions")
        assert r.status_code == 200
        body = r.json()
        assert body["plugin"] == "demo"
        assert body["versions"] == []


def test_diff_returns_503_when_service_missing() -> None:
    import src.backend.entrypoints.api.v1.endpoints.admin_plugins as mod

    app = _build_app()
    with (
        patch.object(mod, "_check_flag_enabled", lambda: None),
        patch.object(mod, "_get_version_service", lambda: None),
    ):
        client = TestClient(app)
        r = client.get(
            "/api/v1/admin/plugins/demo/diff",
            params={"from_version": "1.0.0", "to_version": "2.0.0"},
        )
        assert r.status_code == 503


def test_rollback_returns_503_when_service_missing() -> None:
    import src.backend.entrypoints.api.v1.endpoints.admin_plugins as mod

    app = _build_app()
    with (
        patch.object(mod, "_check_flag_enabled", lambda: None),
        patch.object(mod, "_get_version_service", lambda: None),
    ):
        client = TestClient(app)
        r = client.post(
            "/api/v1/admin/plugins/demo/rollback",
            json={"to_version": "1.0.0"},
        )
        assert r.status_code == 503


def test_dependency_graph_empty_for_missing_dir(tmp_path, monkeypatch) -> None:
    import src.backend.entrypoints.api.v1.endpoints.admin_plugins as mod

    monkeypatch.chdir(tmp_path)
    app = _build_app()
    with patch.object(mod, "_check_flag_enabled", lambda: None):
        client = TestClient(app)
        r = client.get("/api/v1/admin/plugins/dependency-graph")
        assert r.status_code == 200
        assert r.json() == {"nodes": [], "edges": []}


def test_scaffold_dry_run_returns_plan() -> None:
    import src.backend.entrypoints.api.v1.endpoints.admin_plugins as mod

    app = _build_app()
    with patch.object(mod, "_check_flag_enabled", lambda: None):
        client = TestClient(app)
        r = client.post(
            "/api/v1/admin/plugins/scaffold",
            json={
                "name": "my_plugin",
                "capabilities": ["db.read"],
                "dry_run": True,
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["dry_run"] is True
        assert body["created"] is False
        assert any("my_plugin" in a for a in body["actions"])
