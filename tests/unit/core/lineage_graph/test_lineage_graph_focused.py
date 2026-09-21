"""Focused tests for ``core.lineage_graph`` (Wave 4 #73)."""

from __future__ import annotations

import pytest

from src.backend.core.lineage_graph import (
    EdgeKind,
    LineageEdge,
    LineageGraph,
    LineageNode,
    NodeKind,
    get_lineage_graph,
)
from src.backend.core.lineage_graph.graph import reset_lineage_graph


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_lineage_graph()


class TestNodeKind:
    def test_values(self) -> None:
        assert NodeKind.TABLE.value == "table"
        assert NodeKind.ROUTE.value == "route"
        assert NodeKind.TRANSFORM.value == "transform"
        assert NodeKind.SOURCE.value == "source"
        assert NodeKind.SINK.value == "sink"


class TestEdgeKind:
    def test_values(self) -> None:
        assert EdgeKind.READ.value == "read"
        assert EdgeKind.WRITE.value == "write"
        assert EdgeKind.TRANSFORM.value == "transform"
        assert EdgeKind.PUBLISH.value == "publish"
        assert EdgeKind.SUBSCRIBE.value == "subscribe"


class TestLineageNode:
    def test_init(self) -> None:
        n = LineageNode(id="orders", kind=NodeKind.TABLE)
        assert n.id == "orders"
        assert n.kind == NodeKind.TABLE
        assert n.owner == ""
        assert n.description == ""
        assert n.metadata == {}

    def test_init_with_values(self) -> None:
        n = LineageNode(
            id="orders",
            kind=NodeKind.TABLE,
            owner="team-payments",
            description="Orders table",
            metadata={"schema": "public"},
        )
        assert n.owner == "team-payments"


class TestLineageEdge:
    def test_init(self) -> None:
        e = LineageEdge(source="order-create", target="orders", kind=EdgeKind.WRITE)
        assert e.description == ""


class TestLineageGraphInit:
    def test_init_empty(self) -> None:
        g = LineageGraph()
        assert g.size() == 0
        assert g.edge_count() == 0


class TestAddNode:
    def test_add_node(self) -> None:
        g = LineageGraph()
        g.add_node(LineageNode(id="orders", kind=NodeKind.TABLE))
        assert g.size() == 1
        assert g.get_node("orders").kind == NodeKind.TABLE

    def test_add_duplicate_overwrites(self) -> None:
        g = LineageGraph()
        g.add_node(LineageNode(id="x", kind=NodeKind.TABLE))
        g.add_node(LineageNode(id="x", kind=NodeKind.ROUTE))
        assert g.get_node("x").kind == NodeKind.ROUTE


class TestAddEdge:
    def test_add_edge_creates_missing_nodes(self) -> None:
        g = LineageGraph()
        g.add_edge(LineageEdge(source="route-a", target="table-b", kind=EdgeKind.WRITE))
        assert g.size() == 2  # auto-created both nodes
        assert g.edge_count() == 1

    def test_add_edge_uses_existing_nodes(self) -> None:
        g = LineageGraph()
        g.add_node(LineageNode(id="a", kind=NodeKind.ROUTE))
        g.add_node(LineageNode(id="b", kind=NodeKind.TABLE))
        g.add_edge(LineageEdge(source="a", target="b", kind=EdgeKind.WRITE))
        assert g.size() == 2
        assert g.edge_count() == 1


class TestGetNode:
    def test_get_existing(self) -> None:
        g = LineageGraph()
        g.add_node(LineageNode(id="x", kind=NodeKind.TABLE))
        assert g.get_node("x") is not None

    def test_get_missing(self) -> None:
        g = LineageGraph()
        assert g.get_node("missing") is None


class TestListNodes:
    def test_list_all(self) -> None:
        g = LineageGraph()
        g.add_node(LineageNode(id="a", kind=NodeKind.TABLE))
        g.add_node(LineageNode(id="b", kind=NodeKind.ROUTE))
        assert len(g.list_nodes()) == 2


class TestUpstream:
    def test_simple_chain(self) -> None:
        """orders <- payment-api <- invoice-create."""
        g = LineageGraph()
        g.add_node(LineageNode(id="orders", kind=NodeKind.TABLE))
        g.add_node(LineageNode(id="payment-api", kind=NodeKind.ROUTE))
        g.add_node(LineageNode(id="invoice-create", kind=NodeKind.ROUTE))
        g.add_edge(
            LineageEdge(
                source="invoice-create", target="payment-api", kind=EdgeKind.WRITE
            )
        )
        g.add_edge(
            LineageEdge(source="payment-api", target="orders", kind=EdgeKind.WRITE)
        )
        upstream = g.upstream("orders")
        assert "payment-api" in upstream
        assert "invoice-create" in upstream

    def test_no_upstream(self) -> None:
        g = LineageGraph()
        g.add_node(LineageNode(id="x", kind=NodeKind.TABLE))
        assert g.upstream("x") == {}

    def test_max_depth(self) -> None:
        g = LineageGraph()
        for i in range(5):
            g.add_node(LineageNode(id=f"n{i}", kind=NodeKind.TABLE))
        for i in range(4):
            g.add_edge(
                LineageEdge(source=f"n{i + 1}", target=f"n{i}", kind=EdgeKind.WRITE)
            )
        # From n0: depth 0 = n0, depth 1 = n1, depth 2 = n2.
        upstream_d2 = g.upstream("n0", max_depth=2)
        assert "n1" in upstream_d2
        assert "n2" in upstream_d2
        assert "n3" not in upstream_d2


class TestDownstream:
    def test_simple_chain(self) -> None:
        """orders -> reports-api -> dashboard."""
        g = LineageGraph()
        g.add_node(LineageNode(id="orders", kind=NodeKind.TABLE))
        g.add_node(LineageNode(id="reports-api", kind=NodeKind.ROUTE))
        g.add_node(LineageNode(id="dashboard", kind=NodeKind.ROUTE))
        g.add_edge(
            LineageEdge(source="orders", target="reports-api", kind=EdgeKind.READ)
        )
        g.add_edge(
            LineageEdge(source="reports-api", target="dashboard", kind=EdgeKind.PUBLISH)
        )
        downstream = g.downstream("orders")
        assert "reports-api" in downstream
        assert "dashboard" in downstream

    def test_no_downstream(self) -> None:
        g = LineageGraph()
        g.add_node(LineageNode(id="x", kind=NodeKind.TABLE))
        assert g.downstream("x") == {}


class TestPath:
    def test_simple_path(self) -> None:
        g = LineageGraph()
        for n in ["a", "b", "c"]:
            g.add_node(LineageNode(id=n, kind=NodeKind.TABLE))
        g.add_edge(LineageEdge(source="a", target="b", kind=EdgeKind.WRITE))
        g.add_edge(LineageEdge(source="b", target="c", kind=EdgeKind.WRITE))
        path = g.path("a", "c")
        assert path == ["a", "b", "c"]

    def test_no_path(self) -> None:
        g = LineageGraph()
        g.add_node(LineageNode(id="a", kind=NodeKind.TABLE))
        g.add_node(LineageNode(id="b", kind=NodeKind.TABLE))
        assert g.path("a", "b") is None

    def test_same_node(self) -> None:
        g = LineageGraph()
        g.add_node(LineageNode(id="a", kind=NodeKind.TABLE))
        assert g.path("a", "a") == ["a"]


class TestCycleDetection:
    def test_no_cycles(self) -> None:
        g = LineageGraph()
        for n in ["a", "b", "c"]:
            g.add_node(LineageNode(id=n, kind=NodeKind.TABLE))
        g.add_edge(LineageEdge(source="a", target="b", kind=EdgeKind.WRITE))
        g.add_edge(LineageEdge(source="b", target="c", kind=EdgeKind.WRITE))
        assert g.detect_cycles() == []

    def test_cycle_detected(self) -> None:
        g = LineageGraph()
        for n in ["a", "b", "c"]:
            g.add_node(LineageNode(id=n, kind=NodeKind.TABLE))
        # a -> b -> c -> a.
        g.add_edge(LineageEdge(source="a", target="b", kind=EdgeKind.WRITE))
        g.add_edge(LineageEdge(source="b", target="c", kind=EdgeKind.WRITE))
        g.add_edge(LineageEdge(source="c", target="a", kind=EdgeKind.WRITE))
        cycles = g.detect_cycles()
        assert len(cycles) >= 1


class TestClear:
    def test_clear(self) -> None:
        g = LineageGraph()
        g.add_node(LineageNode(id="a", kind=NodeKind.TABLE))
        g.add_edge(LineageEdge(source="a", target="b", kind=EdgeKind.WRITE))
        g.clear()
        assert g.size() == 0
        assert g.edge_count() == 0


class TestToDict:
    def test_export(self) -> None:
        g = LineageGraph()
        g.add_node(LineageNode(id="orders", kind=NodeKind.TABLE))
        g.add_edge(LineageEdge(source="api", target="orders", kind=EdgeKind.WRITE))
        d = g.to_dict()
        assert len(d["nodes"]) == 2  # auto-created 'api'
        assert len(d["edges"]) == 1
        assert d["stats"]["node_count"] == 2


class TestSingleton:
    def test_singleton(self) -> None:
        g1 = get_lineage_graph()
        g2 = get_lineage_graph()
        assert g1 is g2

    def test_reset(self) -> None:
        g1 = get_lineage_graph()
        reset_lineage_graph()
        g2 = get_lineage_graph()
        assert g1 is not g2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import lineage_graph

        assert len(lineage_graph.__all__) == 6


class TestRealisticExample:
    """Realistic: order-to-analytics lineage."""

    def test_order_to_analytics_lineage(self) -> None:
        g = LineageGraph()
        # Layer 1: Source events.
        g.add_node(
            LineageNode(id="user-clicks", kind=NodeKind.SOURCE, owner="analytics")
        )
        g.add_node(
            LineageNode(id="order-create", kind=NodeKind.ROUTE, owner="team-payments")
        )
        g.add_node(
            LineageNode(id="skb-integration", kind=NodeKind.ROUTE, owner="team-skb")
        )
        # Layer 2: Tables.
        g.add_node(LineageNode(id="orders", kind=NodeKind.TABLE, owner="team-payments"))
        g.add_node(
            LineageNode(id="order_events", kind=NodeKind.TABLE, owner="team-payments")
        )
        # Layer 3: Transforms.
        g.add_node(LineageNode(id="daily-revenue", kind=NodeKind.TRANSFORM))
        # Layer 4: Sinks.
        g.add_node(LineageNode(id="dashboard", kind=NodeKind.SINK))
        g.add_node(LineageNode(id="tax-report", kind=NodeKind.SINK))

        # Edges.
        g.add_edge(
            LineageEdge(source="order-create", target="orders", kind=EdgeKind.WRITE)
        )
        g.add_edge(
            LineageEdge(source="skb-integration", target="orders", kind=EdgeKind.WRITE)
        )
        g.add_edge(
            LineageEdge(
                source="order-create", target="order_events", kind=EdgeKind.PUBLISH
            )
        )
        g.add_edge(
            LineageEdge(
                source="user-clicks", target="daily-revenue", kind=EdgeKind.TRANSFORM
            )
        )
        g.add_edge(
            LineageEdge(source="orders", target="daily-revenue", kind=EdgeKind.READ)
        )
        g.add_edge(
            LineageEdge(
                source="daily-revenue", target="dashboard", kind=EdgeKind.PUBLISH
            )
        )
        g.add_edge(
            LineageEdge(source="orders", target="tax-report", kind=EdgeKind.WRITE)
        )

        # What depends on `orders`? (blast radius analysis).
        downstream = g.downstream("orders")
        assert "daily-revenue" in downstream
        assert "dashboard" in downstream
        assert "tax-report" in downstream

        # What feeds into `dashboard`? (lineage analysis).
        upstream = g.upstream("dashboard")
        assert "daily-revenue" in upstream
        assert "orders" in upstream
        assert "user-clicks" in upstream

        # Path from order-create to dashboard.
        path = g.path("order-create", "dashboard")
        assert path is not None
        assert path[0] == "order-create"
        assert path[-1] == "dashboard"

        # No cycles in this design.
        assert g.detect_cycles() == []
