"""Integration tests: cost_attribution + connectors.

Verifies that:
- @track_cost decorator on connector methods records per-tenant cost.
- CostReport aggregations work across multiple connector operations.
- Pure-Python integration (no external DB, no backend API).
"""

from __future__ import annotations

import pytest

from src.backend.core.connectors import (
    BaseConnector,
    ConnectorMetadata,
    get_connector_registry,
)
from src.backend.core.cost_attribution import (
    ResourceType,
    get_cost_registry,
    track_cost,
)


@pytest.fixture(autouse=True)
def _reset():
    """Reset both registries перед каждым test."""
    from src.backend.core.connectors import reset_connector_registry
    from src.backend.core.cost_attribution import reset_cost_attribution

    reset_connector_registry()
    reset_cost_attribution()
    yield
    reset_connector_registry()
    reset_cost_attribution()


# ─── Test fixtures ──────────────────────────────────


class FakePaymentConnector(BaseConnector):
    """Test connector с track_cost-decorated methods."""

    def __init__(self) -> None:
        super().__init__()
        self.call_count = 0

    def metadata(self) -> ConnectorMetadata:
        from src.backend.core.connectors import AuthModel

        return ConnectorMetadata(
            name="payment",
            version="1.0.0",
            category="external",
            auth_model=AuthModel.API_KEY,
        )

    def config_schema(self) -> dict:
        return {"type": "object", "properties": {"api_key": {"type": "string"}}}

    async def health_check(self) -> dict:
        return {"status": "ok"}

    async def test_connection(self, config: dict) -> bool:
        return bool(config.get("api_key"))

    def operations(self) -> list:
        from src.backend.core.connectors import OperationSchema

        return [
            OperationSchema(
                name="createPayment",
                description="Create payment",
            )
        ]

    @track_cost(
        ResourceType.EXTERNAL_API,
        cost_per_unit=0.05,
        tenant_id_arg="tenant_id",
    )
    async def create_payment(self, tenant_id: str, amount: float) -> dict:
        self.call_count += 1
        return {"status": "ok", "amount": amount}


# ─── Integration tests ──────────────────────────────


class TestConnectorCostAttributionBasic:
    async def test_track_cost_records_connector_call(self) -> None:
        """Single call to track_cost-decorated method records one entry."""
        connector = FakePaymentConnector()
        result = await connector.create_payment("tenant-1", 100.0)
        assert result == {"status": "ok", "amount": 100.0}
        assert connector.call_count == 1

        # Verify cost recorded.
        registry = get_cost_registry()
        records = registry.list_records()
        assert len(records) == 1
        assert records[0].tenant_id == "tenant-1"
        assert records[0].resource_type == ResourceType.EXTERNAL_API
        assert records[0].units == 1.0  # default units
        assert records[0].cost_usd == 0.05  # 1 * 0.05

    async def test_track_cost_units_from_arg(self) -> None:
        """track_cost with units_arg uses function arg value."""
        from src.backend.core.cost_attribution import ResourceType, track_cost

        class QuantityConnector(BaseConnector):
            def metadata(self) -> dict:
                return {"name": "quantity"}

            def config_schema(self) -> dict:
                return {}

            async def health_check(self) -> dict:
                return {}

            async def test_connection(self, config: dict) -> bool:
                return True

            def operations(self) -> list:
                return []

            @track_cost(
                ResourceType.LLM_TOKENS,
                cost_per_unit=0.0001,
                tenant_id_arg="tenant_id",
                units_arg="tokens",
            )
            async def call(self, tenant_id: str, tokens: int) -> int:
                return tokens

        c = QuantityConnector()
        await c.call("tenant-a", 1500)
        records = get_cost_registry().list_records()
        assert len(records) == 1
        assert records[0].units == 1500
        assert records[0].cost_usd == 0.15  # 1500 * 0.0001


class TestMultiTenantCostAttribution:
    async def test_multi_tenant_isolation(self) -> None:
        """Per-tenant cost tracking across multiple calls."""
        connector = FakePaymentConnector()
        # Tenant 1 makes 3 calls.
        await connector.create_payment("tenant-1", 100.0)
        await connector.create_payment("tenant-1", 200.0)
        await connector.create_payment("tenant-1", 50.0)
        # Tenant 2 makes 2 calls.
        await connector.create_payment("tenant-2", 75.0)
        await connector.create_payment("tenant-2", 125.0)

        # Verify per-tenant aggregation.
        report = get_cost_registry().generate_report()
        by_tenant = report.by_tenant()
        # Each call: 1 * 0.05 = $0.05.
        assert by_tenant["tenant-1"] == pytest.approx(0.15)  # 3 * 0.05
        assert by_tenant["tenant-2"] == pytest.approx(0.10)  # 2 * 0.05
        assert report.total_cost_usd == pytest.approx(0.25)

    async def test_aggregations_across_calls(self) -> None:
        """by_tenant / by_resource aggregations work."""
        connector = FakePaymentConnector()
        await connector.create_payment("tenant-x", 1.0)
        await connector.create_payment("tenant-y", 2.0)

        report = get_cost_registry().generate_report()
        assert len(report.by_tenant()) == 2
        assert "external_api" in report.by_resource()
        # 2 records.
        assert report.total_units == 2.0


class TestConnectorCatalogIntegration:
    def test_connector_register_with_track_cost(self) -> None:
        """Connector registered в catalog + track_cost on its methods."""
        registry = get_connector_registry()
        connector = FakePaymentConnector()
        registry.register(connector)

        # Verify connector in catalog.
        assert registry.get("payment") is connector
        assert registry.size() == 1

        # Verify operations are listed.
        ops = connector.operations()
        assert len(ops) == 1
        assert ops[0].name == "createPayment"

    def test_search_connector_by_name(self) -> None:
        """Search by name pattern."""
        registry = get_connector_registry()
        # Use a mock connector with explicit name.
        connector = FakePaymentConnector()
        registry.register(connector)
        # Verify lookup by name.
        found = registry.get("payment")
        assert found is connector
        # Verify registry size.
        assert registry.size() >= 1


class TestCombinedFlow:
    async def test_connector_call_aggregates_cost(self) -> None:
        """End-to-end: connector method + @track_cost + CostReport."""
        connector = FakePaymentConnector()
        # Register connector in catalog.
        get_connector_registry().register(connector)

        # Simulate 5 calls across 2 tenants.
        for i in range(3):
            await connector.create_payment("tenant-a", float(i * 10))
        for i in range(2):
            await connector.create_payment("tenant-b", float(i * 10))

        # Verify catalog has 1 entry.
        assert get_connector_registry().size() == 1

        # Verify cost report.
        report = get_cost_registry().generate_report()
        assert report.total_cost_usd == pytest.approx(0.25)  # 5 * 0.05

    async def test_concurrent_calls_track_separately(self) -> None:
        """Concurrent calls from same tenant track correctly."""
        connector = FakePaymentConnector()
        await asyncio.gather(
            *[
                connector.create_payment("tenant-x", float(i))
                for i in range(10)
            ]
        )
        records = get_cost_registry().list_records()
        assert len(records) == 10
        # All for same tenant.
        assert all(r.tenant_id == "tenant-x" for r in records)
        assert get_cost_registry().generate_report().total_cost_usd == pytest.approx(
            0.5
        )


import asyncio
