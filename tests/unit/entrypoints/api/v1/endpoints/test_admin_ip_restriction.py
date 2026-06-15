"""Unit tests for admin IP restriction endpoints."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.core.security.ip_restriction_store import get_ip_restriction_store
from src.backend.entrypoints.api.v1.endpoints.admin_ip_restriction import router


@pytest.fixture(autouse=True)
def reset_store():
    store = get_ip_restriction_store()
    store.update_admin(set(), [])
    store.clear_route_rules()
    yield
    store.update_admin(set(), [])
    store.clear_route_rules()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/admin")
    return TestClient(app)


@pytest.mark.unit
class TestAdminIPRestriction:
    def test_get_snapshot(self, client) -> None:
        get_ip_restriction_store().set_route_rule("/api/v1/auto/foo", ["10.0.0.0/8"])
        response = client.get("/admin/ip-restriction")
        assert response.status_code == 200
        data = response.json()
        assert data["route_rules"]["/api/v1/auto/foo"]["allowed_ips"] == ["10.0.0.0/8"]

    def test_put_global(self, client) -> None:
        response = client.put(
            "/admin/ip-restriction",
            json={"admin_ips": ["192.168.1.0/24"], "admin_routes": ["/admin/*"]},
        )
        assert response.status_code == 200
        snapshot = get_ip_restriction_store().snapshot()
        assert snapshot["admin_ips"] == ["192.168.1.0/24"]
        assert snapshot["admin_routes"] == ["/admin/*"]

    def test_put_route_rule(self, client) -> None:
        response = client.put(
            "/admin/ip-restriction/routes//api/v1/auto/bar",
            json={"allowed_ips": ["127.0.0.1"], "enabled": True},
        )
        assert response.status_code == 200
        snapshot = get_ip_restriction_store().snapshot()
        assert snapshot["route_rules"]["/api/v1/auto/bar"]["allowed_ips"] == [
            "127.0.0.1"
        ]

    def test_delete_route_rule(self, client) -> None:
        store = get_ip_restriction_store()
        store.set_route_rule("/api/v1/auto/baz", ["1.2.3.4"])
        response = client.delete("/admin/ip-restriction/routes//api/v1/auto/baz")
        assert response.status_code == 200
        assert "/api/v1/auto/baz" not in store.snapshot()["route_rules"]

    def test_reload_from_yaml(self, client, monkeypatch, tmp_path) -> None:
        config = tmp_path / "ip_restriction.yaml"
        config.write_text(
            """
admin:
  ips: ["10.0.0.0/8"]
  routes: ["/admin/*"]
routes:
  - path_pattern: "/api/v1/auto/x"
    allowed_ips: ["127.0.0.1"]
""",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "src.backend.entrypoints.api.v1.endpoints.admin_ip_restriction._DEFAULT_CONFIG_PATH",
            config,
        )
        response = client.post("/admin/ip-restriction/reload")
        assert response.status_code == 200
        data = response.json()
        assert data["loaded"] is True
        assert data["snapshot"]["admin_ips"] == ["10.0.0.0/8"]
        assert data["snapshot"]["route_rules"]["/api/v1/auto/x"]["allowed_ips"] == [
            "127.0.0.1"
        ]
