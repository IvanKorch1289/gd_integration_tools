"""Focused tests for ``core.route_contract`` (Wave 1 P0 #25)."""

from __future__ import annotations

import pytest

from src.backend.core.route_contract import (
    DLQPolicy,
    IdempotencyPolicy,
    RetryPolicy,
    RouteContract,
    RouteContractRegistry,
    get_route_contract_registry,
    validate_contract,
)
from src.backend.core.route_contract.contract import BackoffStrategy
from src.backend.core.route_contract.registry import reset_route_contract_registry


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_route_contract_registry()


class TestBackoffStrategy:
    def test_values(self) -> None:
        assert BackoffStrategy.NONE.value == "none"
        assert BackoffStrategy.LINEAR.value == "linear"
        assert BackoffStrategy.EXPONENTIAL.value == "exponential"


class TestRetryPolicy:
    def test_defaults(self) -> None:
        r = RetryPolicy()
        assert r.max_attempts == 3
        assert r.backoff == BackoffStrategy.EXPONENTIAL
        assert r.initial_delay_seconds == 1.0
        assert r.max_delay_seconds == 60.0
        assert "retryable" in r.retryable_failure_classes

    def test_custom(self) -> None:
        r = RetryPolicy(
            max_attempts=5,
            backoff=BackoffStrategy.LINEAR,
            initial_delay_seconds=2.0,
            max_delay_seconds=120.0,
            retryable_failure_classes=("a", "b"),
        )
        assert r.max_attempts == 5
        assert r.backoff == BackoffStrategy.LINEAR


class TestIdempotencyPolicy:
    def test_defaults(self) -> None:
        p = IdempotencyPolicy(key_field="id")
        assert p.key_field == "id"
        assert p.ttl_seconds == 86400
        assert p.backend == "default"

    def test_custom(self) -> None:
        p = IdempotencyPolicy(key_field="order_id", ttl_seconds=3600, backend="redis")
        assert p.backend == "redis"


class TestDLQPolicy:
    def test_defaults(self) -> None:
        p = DLQPolicy(topic="events.orders.dlq")
        assert p.topic == "events.orders.dlq"
        assert p.max_retries == 3
        assert p.include_payload is True

    def test_custom(self) -> None:
        p = DLQPolicy(topic="dlq", max_retries=10, include_payload=False)
        assert p.max_retries == 10
        assert p.include_payload is False


class TestRouteContractDefaults:
    def test_minimal(self) -> None:
        c = RouteContract(route_id="r1")
        assert c.route_id == "r1"
        assert c.input_schema == {}
        assert c.output_schema == {}
        assert c.side_effects == []
        assert c.timeout_seconds == 30.0
        assert c.idempotency_policy is None
        assert c.dlq_policy is None
        assert c.owner == ""
        assert c.slo == {}
        assert c.tags == []

    def test_full(self) -> None:
        c = RouteContract(
            route_id="order-create",
            input_schema={"type": "object", "required": ["order_id"]},
            output_schema={"type": "object"},
            side_effects=["db_write"],
            timeout_seconds=15.0,
            retry_policy=RetryPolicy(max_attempts=5),
            idempotency_policy=IdempotencyPolicy(key_field="order_id"),
            dlq_policy=DLQPolicy(topic="events.orders.dlq"),
            owner="team-payments",
            slo={"latency_p99_ms": 200.0},
            tags=["prod", "critical"],
            description="Create order",
        )
        assert c.retry_policy.max_attempts == 5
        assert c.idempotency_policy.key_field == "order_id"
        assert c.dlq_policy.topic == "events.orders.dlq"
        assert c.owner == "team-payments"
        assert c.description == "Create order"


class TestValidateContract:
    """``validate_contract()`` — PolicyGate."""

    def test_valid_minimal(self) -> None:
        c = RouteContract(
            route_id="r1",
            side_effects=["read_only"],
            timeout_seconds=10.0,
            owner="team-x",
        )
        errors = validate_contract(c)
        assert errors == []

    def test_missing_route_id(self) -> None:
        c = RouteContract(
            route_id="",
            side_effects=["read_only"],
            timeout_seconds=10.0,
            owner="team-x",
        )
        errors = validate_contract(c)
        assert any("route_id" in e for e in errors)

    def test_whitespace_route_id(self) -> None:
        c = RouteContract(
            route_id="   ",
            side_effects=["read_only"],
            timeout_seconds=10.0,
            owner="team-x",
        )
        errors = validate_contract(c)
        assert any("route_id" in e for e in errors)

    def test_zero_timeout(self) -> None:
        c = RouteContract(
            route_id="r1",
            side_effects=["read_only"],
            timeout_seconds=0.0,
            owner="team-x",
        )
        errors = validate_contract(c)
        assert any("timeout_seconds" in e for e in errors)

    def test_negative_timeout(self) -> None:
        c = RouteContract(
            route_id="r1",
            side_effects=["read_only"],
            timeout_seconds=-1.0,
            owner="team-x",
        )
        errors = validate_contract(c)
        assert any("timeout_seconds" in e for e in errors)

    def test_timeout_too_large(self) -> None:
        c = RouteContract(
            route_id="r1",
            side_effects=["read_only"],
            timeout_seconds=600.0,
            owner="team-x",
        )
        errors = validate_contract(c)
        assert any("timeout_seconds" in e for e in errors)

    def test_missing_owner(self) -> None:
        c = RouteContract(
            route_id="r1",
            side_effects=["read_only"],
            timeout_seconds=10.0,
            owner="",
        )
        errors = validate_contract(c)
        assert any("owner" in e for e in errors)

    def test_empty_side_effects(self) -> None:
        c = RouteContract(
            route_id="r1",
            side_effects=[],
            timeout_seconds=10.0,
            owner="team-x",
        )
        errors = validate_contract(c)
        assert any("side_effects" in e for e in errors)

    def test_write_without_idempotency(self) -> None:
        """Write route без idempotency_policy → violation."""
        c = RouteContract(
            route_id="r1",
            side_effects=["db_write"],
            timeout_seconds=10.0,
            owner="team-x",
        )
        errors = validate_contract(c)
        assert any("idempotency_policy" in e for e in errors)

    def test_mq_publish_without_idempotency(self) -> None:
        c = RouteContract(
            route_id="r1",
            side_effects=["mq_publish"],
            timeout_seconds=10.0,
            owner="team-x",
        )
        errors = validate_contract(c)
        assert any("idempotency_policy" in e for e in errors)

    def test_write_with_idempotency_ok(self) -> None:
        c = RouteContract(
            route_id="r1",
            side_effects=["db_write"],
            timeout_seconds=10.0,
            owner="team-x",
            idempotency_policy=IdempotencyPolicy(key_field="order_id"),
        )
        errors = validate_contract(c)
        assert errors == []

    def test_read_only_no_idempotency_required(self) -> None:
        c = RouteContract(
            route_id="r1",
            side_effects=["read_only"],
            timeout_seconds=10.0,
            owner="team-x",
        )
        errors = validate_contract(c)
        assert errors == []

    def test_retry_max_attempts_too_low(self) -> None:
        c = RouteContract(
            route_id="r1",
            side_effects=["read_only"],
            timeout_seconds=10.0,
            owner="team-x",
            retry_policy=RetryPolicy(max_attempts=0),
        )
        errors = validate_contract(c)
        assert any("max_attempts" in e for e in errors)

    def test_retry_max_attempts_too_high(self) -> None:
        c = RouteContract(
            route_id="r1",
            side_effects=["read_only"],
            timeout_seconds=10.0,
            owner="team-x",
            retry_policy=RetryPolicy(max_attempts=20),
        )
        errors = validate_contract(c)
        assert any("max_attempts" in e for e in errors)

    def test_multiple_violations(self) -> None:
        c = RouteContract(
            route_id="",
            side_effects=[],
            timeout_seconds=0.0,
            owner="",
        )
        errors = validate_contract(c)
        # At least 3 violations.
        assert len(errors) >= 3


class TestRegistry:
    def test_register_and_get(self) -> None:
        r = RouteContractRegistry()
        c = RouteContract(route_id="r1", owner="team-x", side_effects=["read_only"])
        r.register(c)
        assert r.get("r1") is c

    def test_register_overwrite(self) -> None:
        r = RouteContractRegistry()
        c1 = RouteContract(route_id="r1", owner="team-x", side_effects=["read_only"])
        c2 = RouteContract(route_id="r1", owner="team-y", side_effects=["read_only"])
        r.register(c1)
        r.register(c2)
        assert r.get("r1").owner == "team-y"

    def test_unregister(self) -> None:
        r = RouteContractRegistry()
        c = RouteContract(route_id="r1", owner="x", side_effects=["read_only"])
        r.register(c)
        r.unregister("r1")
        assert r.get("r1") is None

    def test_unregister_missing(self) -> None:
        r = RouteContractRegistry()
        r.unregister("missing")  # no error

    def test_get_missing(self) -> None:
        r = RouteContractRegistry()
        assert r.get("missing") is None

    def test_list_all(self) -> None:
        r = RouteContractRegistry()
        r.register(RouteContract(route_id="r1", owner="x", side_effects=["read_only"]))
        r.register(RouteContract(route_id="r2", owner="y", side_effects=["read_only"]))
        assert len(r.list_all()) == 2

    def test_list_by_owner(self) -> None:
        r = RouteContractRegistry()
        r.register(RouteContract(route_id="r1", owner="x", side_effects=["read_only"]))
        r.register(RouteContract(route_id="r2", owner="y", side_effects=["read_only"]))
        xs = r.list_by_owner("x")
        assert len(xs) == 1
        assert xs[0].route_id == "r1"

    def test_list_by_tag(self) -> None:
        r = RouteContractRegistry()
        r.register(
            RouteContract(
                route_id="r1",
                owner="x",
                side_effects=["read_only"],
                tags=["prod"],
            )
        )
        r.register(
            RouteContract(
                route_id="r2",
                owner="x",
                side_effects=["read_only"],
                tags=["staging"],
            )
        )
        prod = r.list_by_tag("prod")
        assert len(prod) == 1
        assert prod[0].route_id == "r1"

    def test_size(self) -> None:
        r = RouteContractRegistry()
        assert r.size() == 0
        r.register(RouteContract(route_id="r1", owner="x", side_effects=["read_only"]))
        assert r.size() == 1

    def test_clear(self) -> None:
        r = RouteContractRegistry()
        r.register(RouteContract(route_id="r1", owner="x", side_effects=["read_only"]))
        r.clear()
        assert r.size() == 0


class TestSingleton:
    def test_singleton(self) -> None:
        r1 = get_route_contract_registry()
        r2 = get_route_contract_registry()
        assert r1 is r2

    def test_reset(self) -> None:
        r1 = get_route_contract_registry()
        reset_route_contract_registry()
        r2 = get_route_contract_registry()
        assert r1 is not r2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import route_contract

        assert len(route_contract.__all__) == 7


class TestRealisticExample:
    def test_full_order_route_contract(self) -> None:
        """Realistic example: order creation route."""
        c = RouteContract(
            route_id="order-create",
            input_schema={
                "type": "object",
                "required": ["order_id", "amount", "customer_id"],
                "properties": {
                    "order_id": {"type": "string"},
                    "amount": {"type": "number", "minimum": 0},
                    "customer_id": {"type": "string"},
                },
            },
            output_schema={
                "type": "object",
                "required": ["status", "order_id"],
            },
            side_effects=["db_write"],
            timeout_seconds=15.0,
            retry_policy=RetryPolicy(
                max_attempts=3,
                backoff=BackoffStrategy.EXPONENTIAL,
                initial_delay_seconds=2.0,
            ),
            idempotency_policy=IdempotencyPolicy(
                key_field="order_id",
                ttl_seconds=86400,
                backend="redis",
            ),
            dlq_policy=DLQPolicy(topic="events.orders.dlq"),
            owner="team-payments",
            slo={"latency_p99_ms": 500.0, "availability": 0.999},
            tags=["prod", "critical", "pci"],
            description="Create order with idempotency",
        )
        errors = validate_contract(c)
        assert errors == []
        # Register + lookup.
        registry = get_route_contract_registry()
        registry.register(c)
        assert registry.get("order-create") is c
