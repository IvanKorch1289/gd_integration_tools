"""Focused tests for ``core.cost_attribution`` (Wave 4 #75)."""

from __future__ import annotations

import pytest

from src.backend.core.cost_attribution import (
    CostAttribution,
    CostRecord,
    CostReport,
    ResourceType,
    get_cost_attribution,
    get_cost_registry,
    track_cost,
)
from src.backend.core.cost_attribution.attribution import reset_cost_attribution


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_cost_attribution()


class TestResourceType:
    def test_values(self) -> None:
        assert ResourceType.LLM_TOKENS.value == "llm_tokens"
        assert ResourceType.HTTP_REQUESTS.value == "http_requests"
        assert ResourceType.DB_QUERIES.value == "db_queries"
        assert ResourceType.MQ_MESSAGES.value == "mq_messages"


class TestCostRecord:
    def test_defaults(self) -> None:
        r = CostRecord(
            timestamp=1.0,
            tenant_id="t1",
            route_id="r1",
            resource_type=ResourceType.LLM_TOKENS,
            units=100,
            cost_usd=0.01,
        )
        assert r.agent is None
        assert r.connector is None
        assert r.metadata == {}

    def test_to_dict(self) -> None:
        r = CostRecord(
            timestamp=1.0,
            tenant_id="t1",
            route_id="r1",
            resource_type=ResourceType.LLM_TOKENS,
            units=100,
            cost_usd=0.01,
            agent="alice",
        )
        d = r.to_dict()
        assert d["tenant_id"] == "t1"
        assert d["resource_type"] == "llm_tokens"
        assert d["agent"] == "alice"


class TestCostReportEmpty:
    def test_empty_report(self) -> None:
        r = CostReport(timestamp=0.0)
        assert r.total_cost_usd == 0
        assert r.total_units == 0
        assert r.by_tenant() == {}


class TestCostAttributionInit:
    def test_init(self) -> None:
        ca = CostAttribution()
        assert ca.size() == 0


class TestCostAttributionRecord:
    def test_record_basic(self) -> None:
        ca = CostAttribution()
        rec = ca.record(
            tenant_id="t1",
            route_id="r1",
            resource_type=ResourceType.LLM_TOKENS,
            units=100,
            cost_usd=0.01,
        )
        assert rec.tenant_id == "t1"
        assert rec.units == 100
        assert ca.size() == 1

    def test_list_records(self) -> None:
        ca = CostAttribution()
        ca.record(
            tenant_id="t1",
            route_id="r1",
            resource_type=ResourceType.LLM_TOKENS,
            units=100,
            cost_usd=0.01,
        )
        ca.record(
            tenant_id="t2",
            route_id="r2",
            resource_type=ResourceType.HTTP_REQUESTS,
            units=1,
            cost_usd=0.001,
        )
        assert len(ca.list_records()) == 2

    def test_list_for_tenant(self) -> None:
        ca = CostAttribution()
        ca.record(
            tenant_id="t1",
            route_id="r1",
            resource_type=ResourceType.LLM_TOKENS,
            units=100,
            cost_usd=0.01,
        )
        ca.record(
            tenant_id="t2",
            route_id="r2",
            resource_type=ResourceType.LLM_TOKENS,
            units=200,
            cost_usd=0.02,
        )
        t1_records = ca.list_for_tenant("t1")
        assert len(t1_records) == 1
        assert t1_records[0].tenant_id == "t1"

    def test_list_for_route(self) -> None:
        ca = CostAttribution()
        ca.record(
            tenant_id="t1",
            route_id="r1",
            resource_type=ResourceType.LLM_TOKENS,
            units=100,
            cost_usd=0.01,
        )
        ca.record(
            tenant_id="t1",
            route_id="r2",
            resource_type=ResourceType.HTTP_REQUESTS,
            units=1,
            cost_usd=0.001,
        )
        r1_records = ca.list_for_route("r1")
        assert len(r1_records) == 1

    def test_clear(self) -> None:
        ca = CostAttribution()
        ca.record(
            tenant_id="t1",
            route_id="r1",
            resource_type=ResourceType.LLM_TOKENS,
            units=100,
            cost_usd=0.01,
        )
        ca.clear()
        assert ca.size() == 0

    def test_generate_report(self) -> None:
        ca = CostAttribution()
        ca.record(
            tenant_id="t1",
            route_id="r1",
            resource_type=ResourceType.LLM_TOKENS,
            units=100,
            cost_usd=0.01,
        )
        report = ca.generate_report()
        assert isinstance(report, CostReport)
        assert len(report.records) == 1


class TestCostReportAggregation:
    def test_total_cost(self) -> None:
        ca = CostAttribution()
        ca.record(
            tenant_id="t1",
            route_id="r1",
            resource_type=ResourceType.LLM_TOKENS,
            units=100,
            cost_usd=0.01,
        )
        ca.record(
            tenant_id="t1",
            route_id="r2",
            resource_type=ResourceType.LLM_TOKENS,
            units=200,
            cost_usd=0.02,
        )
        report = ca.generate_report()
        assert report.total_cost_usd == 0.03
        assert report.total_units == 300

    def test_by_tenant(self) -> None:
        ca = CostAttribution()
        ca.record(
            tenant_id="t1",
            route_id="r1",
            resource_type=ResourceType.LLM_TOKENS,
            units=100,
            cost_usd=0.01,
        )
        ca.record(
            tenant_id="t2",
            route_id="r2",
            resource_type=ResourceType.LLM_TOKENS,
            units=200,
            cost_usd=0.05,
        )
        ca.record(
            tenant_id="t1",
            route_id="r3",
            resource_type=ResourceType.HTTP_REQUESTS,
            units=1,
            cost_usd=0.001,
        )
        report = ca.generate_report()
        by_tenant = report.by_tenant()
        assert by_tenant["t1"] == pytest.approx(0.011)
        assert by_tenant["t2"] == pytest.approx(0.05)

    def test_by_route(self) -> None:
        ca = CostAttribution()
        ca.record(
            tenant_id="t1",
            route_id="r1",
            resource_type=ResourceType.LLM_TOKENS,
            units=100,
            cost_usd=0.01,
        )
        ca.record(
            tenant_id="t1",
            route_id="r2",
            resource_type=ResourceType.HTTP_REQUESTS,
            units=1,
            cost_usd=0.001,
        )
        report = ca.generate_report()
        by_route = report.by_route()
        assert "r1" in by_route
        assert "r2" in by_route

    def test_by_resource(self) -> None:
        ca = CostAttribution()
        ca.record(
            tenant_id="t1",
            route_id="r1",
            resource_type=ResourceType.LLM_TOKENS,
            units=100,
            cost_usd=0.01,
        )
        ca.record(
            tenant_id="t1",
            route_id="r1",
            resource_type=ResourceType.HTTP_REQUESTS,
            units=1,
            cost_usd=0.001,
        )
        report = ca.generate_report()
        by_res = report.by_resource()
        assert "llm_tokens" in by_res
        assert "http_requests" in by_res

    def test_by_agent(self) -> None:
        ca = CostAttribution()
        ca.record(
            tenant_id="t1",
            route_id="r1",
            resource_type=ResourceType.LLM_TOKENS,
            units=100,
            cost_usd=0.01,
            agent="alice",
        )
        ca.record(
            tenant_id="t1",
            route_id="r1",
            resource_type=ResourceType.LLM_TOKENS,
            units=200,
            cost_usd=0.02,
            agent="bob",
        )
        report = ca.generate_report()
        by_agent = report.by_agent()
        assert by_agent["alice"] == pytest.approx(0.01)
        assert by_agent["bob"] == pytest.approx(0.02)

    def test_top_consumers(self) -> None:
        ca = CostAttribution()
        for tenant in ["t1", "t2", "t3"]:
            ca.record(
                tenant_id=tenant,
                route_id="r1",
                resource_type=ResourceType.LLM_TOKENS,
                units=100,
                cost_usd=0.01 * (1 if tenant == "t1" else 5 if tenant == "t2" else 3),
                agent="alice",
            )
        report = ca.generate_report()
        top = report.top_consumers(limit=2)
        assert len(top) == 2
        # t2 should be top (cost 0.05).
        assert top[0][1] == pytest.approx(0.05)

    def test_to_dict(self) -> None:
        ca = CostAttribution()
        ca.record(
            tenant_id="t1",
            route_id="r1",
            resource_type=ResourceType.LLM_TOKENS,
            units=100,
            cost_usd=0.01,
        )
        report = ca.generate_report()
        d = report.to_dict()
        assert d["total_cost_usd"] == pytest.approx(0.01)
        assert d["records_count"] == 1
        assert "t1" in d["by_tenant"]


class TestTrackCostDecorator:
    def test_sync_decorator_basic(self) -> None:
        @track_cost(
            ResourceType.LLM_TOKENS,
            cost_per_unit=0.0001,
            tenant_id_arg="tenant_id",
            units_arg="tokens",
        )
        def call_llm(tenant_id: str, tokens: int) -> str:
            return f"ok:{tenant_id}:{tokens}"

        result = call_llm("t1", 100)
        assert result == "ok:t1:100"
        # Check cost recorded.
        registry = get_cost_registry()
        records = registry.list_records()
        assert len(records) == 1
        assert records[0].units == 100
        assert records[0].cost_usd == pytest.approx(0.01)
        assert records[0].tenant_id == "t1"

    async def test_async_decorator_basic(self) -> None:
        @track_cost(
            ResourceType.HTTP_REQUESTS,
            cost_per_unit=0.001,
            tenant_id_arg="tenant_id",
        )
        async def fetch(tenant_id: str) -> str:
            return f"data-for-{tenant_id}"

        result = await fetch("t2")
        assert result == "data-for-t2"
        records = get_cost_registry().list_records()
        assert len(records) == 1
        assert records[0].tenant_id == "t2"
        assert records[0].units == 1.0  # default.

    def test_decorator_with_route_id(self) -> None:
        @track_cost(
            ResourceType.LLM_TOKENS,
            cost_per_unit=0.0001,
            tenant_id_arg="tenant_id",
            route_id_arg="route_id",
            units_arg="tokens",
        )
        def call(tenant_id: str, route_id: str, tokens: int) -> None:
            pass

        call("t1", "order-create", 500)
        records = get_cost_registry().list_records()
        assert records[0].route_id == "order-create"
        assert records[0].units == 500
        assert records[0].cost_usd == pytest.approx(0.05)

    def test_decorator_default_units(self) -> None:
        @track_cost(
            ResourceType.HTTP_REQUESTS,
            cost_per_unit=0.001,
            tenant_id_arg="tenant_id",
        )
        def req(tenant_id: str) -> None:
            pass

        req("t1")
        records = get_cost_registry().list_records()
        assert records[0].units == 1.0  # default units_default.


class TestSingleton:
    def test_singleton(self) -> None:
        r1 = get_cost_registry()
        r2 = get_cost_attribution()
        assert r1 is r2

    def test_reset(self) -> None:
        r1 = get_cost_registry()
        reset_cost_attribution()
        r2 = get_cost_registry()
        assert r1 is not r2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import cost_attribution

        assert len(cost_attribution.__all__) == 7


class TestRealisticExample:
    """Realistic: monthly LLM + API cost для multi-tenant SaaS."""

    def test_monthly_cost_breakdown(self) -> None:
        ca = CostAttribution()

        # Tenant t1: 1M LLM tokens + 1000 API calls.
        ca.record(
            tenant_id="t1",
            route_id="order-create",
            resource_type=ResourceType.LLM_TOKENS,
            units=1_000_000,
            cost_usd=0.0001 * 1_000_000,  # $100
            agent="alice",
        )
        ca.record(
            tenant_id="t1",
            route_id="skb-integration",
            resource_type=ResourceType.EXTERNAL_API,
            units=1000,
            cost_usd=0.01 * 1000,  # $10
        )

        # Tenant t2: 500K LLM tokens + 500 API calls.
        ca.record(
            tenant_id="t2",
            route_id="dadata-enrich",
            resource_type=ResourceType.LLM_TOKENS,
            units=500_000,
            cost_usd=0.0001 * 500_000,  # $50
            agent="bob",
        )
        ca.record(
            tenant_id="t2",
            route_id="skb-integration",
            resource_type=ResourceType.EXTERNAL_API,
            units=500,
            cost_usd=0.01 * 500,  # $5
        )

        report = ca.generate_report()
        assert report.total_cost_usd == pytest.approx(165.0)

        # Top consumer: t1 (110 USD).
        top = report.top_consumers(limit=3)
        assert top[0][0] == ("t1", "order-create", "alice")
        assert top[0][1] == pytest.approx(100.0)

        # By tenant.
        by_tenant = report.by_tenant()
        assert by_tenant["t1"] == pytest.approx(110.0)
        assert by_tenant["t2"] == pytest.approx(55.0)
