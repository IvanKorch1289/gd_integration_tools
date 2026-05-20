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


def test_dependency_graph_with_real_extension(tmp_path, monkeypatch) -> None:
    """Sprint 14 K5 W3 — реальный плагин в extensions/ → 1 node + N edges."""
    import src.backend.entrypoints.api.v1.endpoints.admin_plugins as mod

    monkeypatch.chdir(tmp_path)
    plugin_dir = tmp_path / "extensions" / "demo"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.toml").write_text(
        'name = "demo"\n'
        'version = "1.0.0"\n'
        'requires_core = ">=0.2,<1.0"\n'
        'entry_class = "extensions.demo.plugin.Demo"\n'
        "[compatibility]\n"
        'requires_plugins = { other = ">=1.0,<2.0" }\n',
        encoding="utf-8",
    )

    app = _build_app()
    with patch.object(mod, "_check_flag_enabled", lambda: None):
        client = TestClient(app)
        r = client.get("/api/v1/admin/plugins/dependency-graph")
        assert r.status_code == 200
        body = r.json()
        assert any(n["id"] == "demo" for n in body["nodes"])
        # requires_plugins даёт ребро demo→other.
        assert any(
            e["source"] == "demo" and e["target"] == "other"
            for e in body["edges"]
        )


def test_scaffold_real_create_invokes_codegen(tmp_path, monkeypatch) -> None:
    """Sprint 14 K5 W6 — без dry_run вызывает ``tools.codegen_plugin.scaffold_plugin``."""
    import src.backend.entrypoints.api.v1.endpoints.admin_plugins as mod

    fake_path = tmp_path / "extensions" / "my_plugin"
    fake_path.mkdir(parents=True)
    calls: list[str] = []

    def _fake_scaffold(name: str):
        calls.append(name)
        return fake_path

    import tools.codegen_plugin as codegen_mod

    app = _build_app()
    with (
        patch.object(mod, "_check_flag_enabled", lambda: None),
        patch.object(codegen_mod, "scaffold_plugin", _fake_scaffold),
    ):
        client = TestClient(app)
        r = client.post(
            "/api/v1/admin/plugins/scaffold",
            json={"name": "my_plugin", "dry_run": False},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is True
    assert body["dry_run"] is False
    assert body["path"] == str(fake_path)
    assert calls == ["my_plugin"]
