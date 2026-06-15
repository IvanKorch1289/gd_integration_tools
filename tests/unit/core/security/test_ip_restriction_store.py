"""Unit tests for IPRestrictionStore."""

from __future__ import annotations

import pytest

from src.backend.core.security.ip_restriction_store import (
    IPRestrictionStore,
    get_ip_restriction_store,
)


@pytest.mark.unit
class TestIPRestrictionStore:
    """Tests for :class:`IPRestrictionStore`."""

    @pytest.fixture(autouse=True)
    def reset_store(self):
        store = get_ip_restriction_store()
        store.update_admin(set(), [])
        store.clear_route_rules()
        yield
        store.update_admin(set(), [])
        store.clear_route_rules()

    def test_singleton(self) -> None:
        assert get_ip_restriction_store() is get_ip_restriction_store()
        assert isinstance(IPRestrictionStore(), IPRestrictionStore)

    def test_update_admin(self) -> None:
        store = get_ip_restriction_store()
        store.update_admin(admin_ips={"1.2.3.4"}, admin_routes=["/admin/*"])
        snapshot = store.snapshot()
        assert snapshot["admin_ips"] == ["1.2.3.4"]
        assert snapshot["admin_routes"] == ["/admin/*"]

    def test_set_and_remove_route_rule(self) -> None:
        store = get_ip_restriction_store()
        store.set_route_rule("/api/v1/auto/foo", ["10.0.0.0/8"])
        assert "/api/v1/auto/foo" in store.snapshot()["route_rules"]
        store.remove_route_rule("/api/v1/auto/foo")
        assert store.snapshot()["route_rules"] == {}

    def test_is_allowed_public(self) -> None:
        store = get_ip_restriction_store()
        assert store.is_allowed("/public", "1.2.3.4") is True

    def test_is_allowed_admin(self) -> None:
        store = get_ip_restriction_store()
        store.update_admin(admin_ips={"192.168.1.1"}, admin_routes=["/admin/*"])
        assert store.is_allowed("/admin/users", "192.168.1.1") is True
        assert store.is_allowed("/admin/users", "10.0.0.1") is False

    def test_is_allowed_subnet(self) -> None:
        store = get_ip_restriction_store()
        store.update_admin(admin_ips={"10.0.0.0/8"}, admin_routes=["/admin/*"])
        assert store.is_allowed("/admin/users", "10.5.5.5") is True
        assert store.is_allowed("/admin/users", "192.168.1.1") is False

    def test_is_allowed_per_route(self) -> None:
        store = get_ip_restriction_store()
        store.set_route_rule("/api/v1/auto/foo", ["127.0.0.1"])
        assert store.is_allowed("/api/v1/auto/foo", "127.0.0.1") is True
        assert store.is_allowed("/api/v1/auto/foo", "10.0.0.1") is False
        assert store.is_allowed("/api/v1/auto/bar", "10.0.0.1") is True

    def test_is_allowed_per_route_disabled(self) -> None:
        store = get_ip_restriction_store()
        store.update_admin(admin_ips={"10.0.0.1"}, admin_routes=["/admin/*"])
        store.set_route_rule("/api/v1/auto/foo", ["127.0.0.1"], enabled=False)
        assert store.is_allowed("/api/v1/auto/foo", "10.0.0.1") is True

    def test_per_route_priority_over_admin(self) -> None:
        store = get_ip_restriction_store()
        store.update_admin(admin_ips={"10.0.0.1"}, admin_routes=["/admin/*"])
        store.set_route_rule("/admin/foo", ["192.168.1.1"])
        assert store.is_allowed("/admin/foo", "192.168.1.1") is True
        assert store.is_allowed("/admin/foo", "10.0.0.1") is False

    def test_invalid_client_ip(self) -> None:
        store = get_ip_restriction_store()
        store.update_admin(admin_ips={"192.168.1.1"}, admin_routes=["/admin/*"])
        assert store.is_allowed("/admin/users", "bad-ip") is False

    def test_reload_from_yaml(self, tmp_path) -> None:
        store = get_ip_restriction_store()
        config = tmp_path / "ip_restriction.yaml"
        config.write_text(
            """
admin:
  ips: ["10.0.0.0/8"]
  routes: ["/admin/*"]
routes:
  - path_pattern: "/api/v1/auto/foo"
    allowed_ips: ["127.0.0.1"]
    enabled: true
""",
            encoding="utf-8",
        )
        assert store.reload_from_yaml(config) is True
        snapshot = store.snapshot()
        assert snapshot["admin_ips"] == ["10.0.0.0/8"]
        assert snapshot["admin_routes"] == ["/admin/*"]
        assert snapshot["route_rules"]["/api/v1/auto/foo"]["allowed_ips"] == [
            "127.0.0.1"
        ]

    def test_reload_from_missing_yaml(self, tmp_path) -> None:
        store = get_ip_restriction_store()
        assert store.reload_from_yaml(tmp_path / "missing.yaml") is False

    def test_clear_route_rules(self) -> None:
        store = get_ip_restriction_store()
        store.set_route_rule("/a", ["1.2.3.4"])
        store.set_route_rule("/b", ["5.6.7.8"])
        store.clear_route_rules()
        assert store.snapshot()["route_rules"] == {}
