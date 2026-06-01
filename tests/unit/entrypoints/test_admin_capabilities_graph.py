# ruff: noqa: S101
"""Sprint 14 K5 W5 — smoke на ``GET /admin/capabilities/graph``.

План S14 §C T-2: эндпоинт ранее не покрывался тестами. Проверяет
два сценария:

* пустой ``extensions/`` → ``{"nodes": [], "edges": []}``;
* одна demo-extension → ≥ 1 plugin-node + 2 ребра на capability.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_app() -> FastAPI:
    from src.backend.entrypoints.api.v1.endpoints.admin_capabilities import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/admin")
    return app


def _write_demo_plugin(extensions_dir: Path) -> None:
    """Создаёт минимальный V11 manifest с одной capability."""
    plugin_dir = extensions_dir / "demo"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.toml").write_text(
        'name = "demo"\n'
        'version = "1.0.0"\n'
        'requires_core = ">=0.2,<1.0"\n'
        'entry_class = "extensions.demo.plugin.Demo"\n'
        "capabilities = [\n"
        '    { name = "db.read", scope = "orders" },\n'
        "]\n",
        encoding="utf-8",
    )


def test_capabilities_graph_empty_for_missing_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = _build_app()
    client = TestClient(app)
    r = client.get("/api/v1/admin/capabilities/graph")
    assert r.status_code == 200
    assert r.json() == {"nodes": [], "edges": []}


def test_capabilities_graph_with_one_demo_plugin(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    extensions_dir = tmp_path / "extensions"
    _write_demo_plugin(extensions_dir)

    app = _build_app()
    client = TestClient(app)
    r = client.get("/api/v1/admin/capabilities/graph")
    assert r.status_code == 200
    body = r.json()

    node_kinds = {n["kind"] for n in body["nodes"]}
    assert {"plugin", "capability", "resource"}.issubset(node_kinds)

    plugin_nodes = [n for n in body["nodes"] if n["kind"] == "plugin"]
    assert any(n["label"] == "demo" for n in plugin_nodes)

    # Одна capability → 2 ребра: plugin→cap, cap→resource.
    assert len(body["edges"]) == 2
    plugin_to_cap = [e for e in body["edges"] if e["source"] == "plugin:demo"]
    assert plugin_to_cap and plugin_to_cap[0]["target"] == "cap:db.read"
    assert plugin_to_cap[0]["label"] == "orders"
