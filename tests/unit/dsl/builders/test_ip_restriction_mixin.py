"""Unit tests for RouteBuilder.ip_restriction DSL mixin."""

from __future__ import annotations

import pytest

from src.backend.core.security.ip_restriction_store import get_ip_restriction_store
from src.backend.dsl.builders.base import RouteBuilder


@pytest.fixture(autouse=True)
def reset_store():
    store = get_ip_restriction_store()
    store.update_admin(set(), [])
    store.clear_route_rules()
    yield
    store.update_admin(set(), [])
    store.clear_route_rules()


@pytest.mark.unit
class TestIPRestrictionMixin:
    def test_default_pattern(self) -> None:
        builder = RouteBuilder.from_("payments.import", source="timer:60s")
        result = builder.ip_restriction(["10.0.0.0/8", "127.0.0.1"])
        assert result is builder

        snapshot = get_ip_restriction_store().snapshot()
        rule = snapshot["route_rules"]["/api/v1/auto/payments.import"]
        assert rule["allowed_ips"] == ["10.0.0.0/8", "127.0.0.1"]
        assert rule["enabled"] is True

    def test_explicit_path_pattern(self) -> None:
        RouteBuilder.from_("orders.create", source="timer:60s").ip_restriction(
            ["192.168.0.0/16"], path_pattern="/api/v1/custom/orders"
        )
        snapshot = get_ip_restriction_store().snapshot()
        rule = snapshot["route_rules"]["/api/v1/custom/orders"]
        assert rule["allowed_ips"] == ["192.168.0.0/16"]

    def test_disabled_rule(self) -> None:
        RouteBuilder.from_("shipments.track", source="timer:60s").ip_restriction(
            ["10.0.0.0/8"], enabled=False
        )
        snapshot = get_ip_restriction_store().snapshot()
        rule = snapshot["route_rules"]["/api/v1/auto/shipments.track"]
        assert rule["enabled"] is False
