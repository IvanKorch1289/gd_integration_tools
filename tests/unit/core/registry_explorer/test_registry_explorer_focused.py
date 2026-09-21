"""Focused tests for ``core.registry_explorer`` (Wave 2 DX #54)."""

from __future__ import annotations

import pytest

from src.backend.core.registry_explorer import (
    ActionEntry,
    ConnectorEntry,
    RegistryExplorer,
    RouteEntry,
    get_registry_explorer,
)
from src.backend.core.registry_explorer.explorer import reset_registry_explorer


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_registry_explorer()


class TestRouteEntry:
    def test_defaults(self) -> None:
        r = RouteEntry(id="r1")
        assert r.source == ""
        assert r.timeout_seconds == 30.0
        assert r.tags == []
        assert r.tenant_id == "*"

    def test_with_values(self) -> None:
        r = RouteEntry(
            id="r1",
            source="timer:60s",
            description="Test route",
            owner="team-x",
            timeout_seconds=10.0,
            tags=["prod", "critical"],
        )
        assert r.owner == "team-x"
        assert "critical" in r.tags


class TestConnectorEntry:
    def test_defaults(self) -> None:
        c = ConnectorEntry(name="skb")
        assert c.category == ""
        assert c.auth == ""
        assert c.tags == []


class TestActionEntry:
    def test_defaults(self) -> None:
        a = ActionEntry(name="orders.create")
        assert a.params == []
        assert a.side_effect == ""


class TestExplorerInit:
    def test_init_empty(self) -> None:
        e = RegistryExplorer()
        assert e.route_count() == 0
        assert e.connector_count() == 0
        assert e.action_count() == 0
        assert e.summary() == {"routes": 0, "connectors": 0, "actions": 0}


class TestRoutesCRUD:
    def test_register_and_find(self) -> None:
        e = RegistryExplorer()
        e.register_route(RouteEntry(id="r1", owner="team-x"))
        assert e.find_route("r1") is not None

    def test_find_missing(self) -> None:
        e = RegistryExplorer()
        assert e.find_route("missing") is None

    def test_list_routes(self) -> None:
        e = RegistryExplorer()
        e.register_route(RouteEntry(id="a"))
        e.register_route(RouteEntry(id="b"))
        assert len(e.list_routes()) == 2

    def test_list_by_owner(self) -> None:
        e = RegistryExplorer()
        e.register_route(RouteEntry(id="a", owner="team-x"))
        e.register_route(RouteEntry(id="b", owner="team-y"))
        e.register_route(RouteEntry(id="c", owner="team-x"))
        xs = e.list_routes_by_owner("team-x")
        assert len(xs) == 2

    def test_list_by_tag(self) -> None:
        e = RegistryExplorer()
        e.register_route(RouteEntry(id="a", tags=["prod"]))
        e.register_route(RouteEntry(id="b", tags=["dev"]))
        e.register_route(RouteEntry(id="c", tags=["prod", "critical"]))
        prod = e.list_routes_by_tag("prod")
        assert len(prod) == 2


class TestSearchRoutes:
    def test_search_by_owner(self) -> None:
        e = RegistryExplorer()
        e.register_route(RouteEntry(id="a", owner="x"))
        e.register_route(RouteEntry(id="b", owner="y"))
        result = e.search_routes(owner="x")
        assert len(result) == 1
        assert result[0].id == "a"

    def test_search_by_tag(self) -> None:
        e = RegistryExplorer()
        e.register_route(RouteEntry(id="a", tags=["critical"]))
        result = e.search_routes(tag="critical")
        assert len(result) == 1

    def test_search_by_tenant(self) -> None:
        e = RegistryExplorer()
        e.register_route(RouteEntry(id="a", tenant_id="t1"))
        e.register_route(RouteEntry(id="b", tenant_id="*"))
        result = e.search_routes(tenant_id="t1")
        assert len(result) == 1

    def test_search_multi_criteria(self) -> None:
        e = RegistryExplorer()
        e.register_route(RouteEntry(id="a", owner="x", tags=["prod"], tenant_id="t1"))
        e.register_route(RouteEntry(id="b", owner="x", tags=["dev"], tenant_id="t1"))
        result = e.search_routes(owner="x", tag="prod", tenant_id="t1")
        assert len(result) == 1
        assert result[0].id == "a"

    def test_search_empty(self) -> None:
        e = RegistryExplorer()
        e.register_route(RouteEntry(id="a"))
        result = e.search_routes(owner="nonexistent")
        assert result == []


class TestConnectorsCRUD:
    def test_register_and_find(self) -> None:
        e = RegistryExplorer()
        e.register_connector(ConnectorEntry(name="skb", category="external"))
        assert e.find_connector("skb") is not None

    def test_list_by_category(self) -> None:
        e = RegistryExplorer()
        e.register_connector(ConnectorEntry(name="skb", category="external"))
        e.register_connector(ConnectorEntry(name="dadata", category="external"))
        e.register_connector(ConnectorEntry(name="postgres", category="db"))
        ext = e.list_connectors_by_category("external")
        assert len(ext) == 2

    def test_list_by_tag(self) -> None:
        e = RegistryExplorer()
        e.register_connector(ConnectorEntry(name="skb", tags=["prod", "critical"]))
        e.register_connector(ConnectorEntry(name="dadata", tags=["prod"]))
        crit = e.list_connectors_by_tag("critical")
        assert len(crit) == 1
        assert crit[0].name == "skb"


class TestActionsCRUD:
    def test_register_and_find(self) -> None:
        e = RegistryExplorer()
        e.register_action(ActionEntry(name="orders.create", side_effect="write"))
        assert e.find_action("orders.create").side_effect == "write"

    def test_list_all(self) -> None:
        e = RegistryExplorer()
        e.register_action(ActionEntry(name="a"))
        e.register_action(ActionEntry(name="b"))
        assert e.action_count() == 2


class TestSummary:
    def test_summary(self) -> None:
        e = RegistryExplorer()
        e.register_route(RouteEntry(id="r1"))
        e.register_route(RouteEntry(id="r2"))
        e.register_connector(ConnectorEntry(name="c1"))
        e.register_action(ActionEntry(name="a1"))
        s = e.summary()
        assert s == {"routes": 2, "connectors": 1, "actions": 1}


class TestToDict:
    def test_export(self) -> None:
        e = RegistryExplorer()
        e.register_route(
            RouteEntry(id="r1", source="timer:60s", owner="team-x", tags=["prod"])
        )
        e.register_connector(
            ConnectorEntry(name="skb", category="external", auth="oauth2")
        )
        e.register_action(ActionEntry(name="orders.create", side_effect="write"))
        d = e.to_dict()
        assert len(d["routes"]) == 1
        assert len(d["connectors"]) == 1
        assert len(d["actions"]) == 1
        assert d["summary"]["routes"] == 1
        assert d["routes"][0]["id"] == "r1"
        assert d["connectors"][0]["auth"] == "oauth2"
        assert d["actions"][0]["side_effect"] == "write"


class TestClear:
    def test_clear(self) -> None:
        e = RegistryExplorer()
        e.register_route(RouteEntry(id="r1"))
        e.register_connector(ConnectorEntry(name="c1"))
        e.register_action(ActionEntry(name="a1"))
        e.clear()
        assert e.route_count() == 0
        assert e.connector_count() == 0
        assert e.action_count() == 0


class TestSingleton:
    def test_singleton(self) -> None:
        e1 = get_registry_explorer()
        e2 = get_registry_explorer()
        assert e1 is e2

    def test_reset(self) -> None:
        e1 = get_registry_explorer()
        reset_registry_explorer()
        e2 = get_registry_explorer()
        assert e1 is not e2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import registry_explorer

        assert len(registry_explorer.__all__) == 9


class TestRealisticExample:
    """Realistic: Streamlit dashboard data provider."""

    def test_streamlit_dashboard_data(self) -> None:
        explorer = get_registry_explorer()
        # Register sample routes.
        explorer.register_route(
            RouteEntry(
                id="order-create",
                source="timer:60s|api=skb",
                owner="team-payments",
                timeout_seconds=30.0,
                tags=["prod", "critical"],
            )
        )
        explorer.register_route(
            RouteEntry(
                id="dadata-enrich",
                source="action:order-create",
                owner="team-payments",
                timeout_seconds=5.0,
                tags=["prod"],
            )
        )
        # Register connectors.
        explorer.register_connector(
            ConnectorEntry(
                name="skb",
                category="external",
                auth="oauth2",
                base_url="https://skb.example.com/v1",
            )
        )
        explorer.register_connector(
            ConnectorEntry(name="dadata", category="external", auth="api_key")
        )
        # Register actions.
        explorer.register_action(
            ActionEntry(
                name="orders.create", side_effect="write", owner="team-payments"
            )
        )

        # Streamlit queries.
        assert explorer.summary() == {"routes": 2, "connectors": 2, "actions": 1}
        # Critical routes.
        crit = explorer.list_routes_by_tag("critical")
        assert len(crit) == 1
        assert crit[0].id == "order-create"
        # team-payments routes.
        team_routes = explorer.search_routes(owner="team-payments")
        assert len(team_routes) == 2
        # External connectors.
        ext = explorer.list_connectors_by_category("external")
        assert len(ext) == 2
        # Full export for UI.
        d = explorer.to_dict()
        assert d["summary"]["routes"] == 2
