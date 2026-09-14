"""Focused tests for ``core.route_test_dsl`` (Wave 2 DX #27).

Цель: покрыть RouteTest DSL на 100% — given/when/then fluent API.
"""

from __future__ import annotations

import asyncio

import pytest

from src.backend.core.route_test_dsl import (
    AssertionResult,
    ExpectationType,
    RouteTest,
    RouteTestResult,
    RouteTestRunner,
    get_route_test_runner,
)
from src.backend.core.route_test_dsl.spec import (
    _ExpectStep,
    _MetricCapture,
    _ThenStep,
    reset_route_test_runner,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_route_test_runner()


def _route_factory(payload):
    """Simple sync route."""
    if payload.get("fail"):
        raise ValueError("test failure")
    return {"status": "ok", "id": payload.get("id", "default")}


async def _async_route(payload):
    await asyncio.sleep(0)
    return {"status": "async_ok", "payload": payload}


class TestRouteTestFluentAPI:
    """Test fluent API returns self for chaining."""

    def test_given_returns_self(self) -> None:
        spec = RouteTest("test1")
        assert spec.given("setup") is spec

    def test_when_returns_self(self) -> None:
        spec = RouteTest("test1")
        assert spec.when("execute") is spec

    def test_then_returns_self(self) -> None:
        spec = RouteTest("test1")
        assert spec.then("assert", expected=1) is spec

    def test_then_truthy_returns_self(self) -> None:
        spec = RouteTest("test1")
        assert spec.then_truthy("assert") is spec

    def test_then_raises_returns_self(self) -> None:
        spec = RouteTest("test1")
        assert spec.then_raises("raises", ValueError) is spec

    def test_expect_metric_returns_self(self) -> None:
        spec = RouteTest("test1")
        assert spec.expect_metric("counter") is spec

    def test_expect_audit_event_returns_self(self) -> None:
        spec = RouteTest("test1")
        assert spec.expect_audit_event("event.type") is spec

    def test_expect_dlq_returns_self(self) -> None:
        spec = RouteTest("test1")
        assert spec.expect_dlq_on_failure(ValueError) is spec

    def test_expect_idempotency_returns_self(self) -> None:
        spec = RouteTest("test1")
        assert spec.expect_idempotency("key-1") is spec


class TestRouteTestSpecInternal:
    """Internal state of RouteTestSpec."""

    def test_spec_name(self) -> None:
        spec = RouteTest("my_test")
        assert spec.spec.name == "my_test"

    def test_givens_accumulate(self) -> None:
        spec = RouteTest("t").given("a", x=1).given("b", y=2)
        assert len(spec.spec.givens) == 2
        assert spec.spec.givens[0].description == "a"
        assert spec.spec.givens[0].payload == {"x": 1}
        assert spec.spec.givens[1].payload == {"y": 2}

    def test_when_sets_description(self) -> None:
        spec = RouteTest("t").when("execute step")
        assert spec.spec.when_description == "execute step"

    def test_thens_accumulate(self) -> None:
        spec = (
            RouteTest("t")
            .then("a", expected=1)
            .then("b", expected=2)
            .then_truthy("c")
            .then_raises("d", KeyError)
        )
        assert len(spec.spec.then_steps) == 4
        assert spec.spec.then_steps[0].comparator == "eq"
        assert spec.spec.then_steps[2].comparator == "truthy"
        assert spec.spec.then_steps[3].comparator == "raises"

    def test_expect_steps_accumulate(self) -> None:
        spec = (
            RouteTest("t")
            .expect_metric("counter1", 5)
            .expect_audit_event("user.created")
            .expect_dlq_on_failure(ValueError)
            .expect_idempotency("k1")
        )
        assert len(spec.spec.expect_steps) == 4


class TestExpectationType:
    def test_values(self) -> None:
        assert ExpectationType.RETURN_VALUE.value == "return_value"
        assert ExpectationType.METRIC.value == "metric"
        assert ExpectationType.AUDIT_EVENT.value == "audit_event"
        assert ExpectationType.DLQ_ON_FAILURE.value == "dlq_on_failure"
        assert ExpectationType.IDEMPOTENCY.value == "idempotency"
        assert ExpectationType.EXCEPTION_TYPE.value == "exception_type"


class TestAssertionResult:
    def test_defaults(self) -> None:
        a = AssertionResult(
            expectation_type=ExpectationType.RETURN_VALUE,
            description="d",
            passed=True,
        )
        assert a.actual is None
        assert a.expected is None
        assert a.error is None


class TestRouteTestResult:
    def test_defaults(self) -> None:
        r = RouteTestResult(name="t", passed=True)
        assert r.assertions == []
        assert r.route_output is None
        assert r.route_error is None
        assert r.duration_ms == 0.0
        assert r.passed_count == 0
        assert r.failed_count == 0

    def test_passed_count(self) -> None:
        r = RouteTestResult(name="t", passed=False)
        r.assertions = [
            AssertionResult(ExpectationType.RETURN_VALUE, "a", passed=True),
            AssertionResult(ExpectationType.RETURN_VALUE, "b", passed=False),
            AssertionResult(ExpectationType.METRIC, "c", passed=True),
        ]
        assert r.passed_count == 2
        assert r.failed_count == 1


class TestRouteTestRunnerInit:
    def test_init(self) -> None:
        runner = RouteTestRunner()
        assert runner._captures == {}


class TestRunSync:
    """Sync route execution."""

    def test_sync_route_pass(self) -> None:
        spec = (
            RouteTest("t")
            .given("valid payload", id="o1")
            .when("call route")
            .then("status is ok", expected={"status": "ok", "id": "o1"})
        )
        result = spec.run(_route_factory)
        assert result.passed
        assert result.route_output == {"status": "ok", "id": "o1"}
        assert len(result.assertions) == 1
        assert result.assertions[0].passed

    def test_sync_route_assertion_fail(self) -> None:
        spec = (
            RouteTest("t")
            .given("payload", id="o1")
            .when("call")
            .then("expect wrong value", expected="WRONG")
        )
        result = spec.run(_route_factory)
        assert result.passed is False
        assert len(result.assertions) == 1
        assert result.assertions[0].passed is False
        assert "WRONG" in result.assertions[0].error

    def test_sync_route_no_givens(self) -> None:
        spec = RouteTest("t").when("call").then_truthy("truthy result")
        result = spec.run(_route_factory)
        assert result.passed
        assert result.assertions[0].passed

    def test_sync_route_multiple_thens(self) -> None:
        spec = (
            RouteTest("t")
            .given("payload", id="o1")
            .when("call")
            .then("status ok", expected="ok")
            .then("id is o1", expected="o1")
        )
        result = spec.run(_route_factory)
        assert result.passed is False
        # Second then fails (output is dict, expected is "o1").
        assert result.assertions[1].passed is False


class TestRunAsync:
    """Async route execution."""

    def test_async_route(self) -> None:
        spec = (
            RouteTest("t")
            .given("payload", x=1)
            .when("async call")
            .then_truthy("has status")
        )
        result = spec.run(_async_route)
        assert result.passed
        assert result.route_output["status"] == "async_ok"


class TestExpectationAssertion:
    """Test metric / audit expectation assertion."""

    def test_metric_recorded_passes(self) -> None:
        runner = RouteTestRunner()
        runner.record_metric("t1", "counter_a", 1)
        capture = runner._captures["t1"]

        assertion = runner._evaluate_expect(
            _ExpectStep(
                description="counter_a >= 1",
                expectation_type=ExpectationType.METRIC,
                expected=1,
                metric_name="counter_a",
            ),
            capture,
        )
        assert assertion.passed

    def test_metric_not_recorded_fails(self) -> None:
        runner = RouteTestRunner()
        # No metric recorded.
        capture = _MetricCapture()

        assertion = runner._evaluate_expect(
            _ExpectStep(
                description="counter_a >= 1",
                expectation_type=ExpectationType.METRIC,
                expected=1,
                metric_name="counter_a",
            ),
            capture,
        )
        assert assertion.passed is False

    def test_audit_event_recorded_passes(self) -> None:
        runner = RouteTestRunner()
        runner.record_audit_event("t1", "user.created")
        capture = runner._captures["t1"]

        assertion = runner._evaluate_expect(
            _ExpectStep(
                description="audit user.created",
                expectation_type=ExpectationType.AUDIT_EVENT,
                audit_event_type="user.created",
            ),
            capture,
        )
        assert assertion.passed

    def test_audit_event_not_recorded_fails(self) -> None:
        runner = RouteTestRunner()
        capture = _MetricCapture()

        assertion = runner._evaluate_expect(
            _ExpectStep(
                description="audit missing",
                expectation_type=ExpectationType.AUDIT_EVENT,
                audit_event_type="missing.event",
            ),
            capture,
        )
        assert assertion.passed is False

    def test_idempotency_passes(self) -> None:
        runner = RouteTestRunner()
        capture = _MetricCapture()
        assertion = runner._evaluate_expect(
            _ExpectStep(
                description="idempotency key=k1",
                expectation_type=ExpectationType.IDEMPOTENCY,
                idempotency_key="k1",
            ),
            capture,
        )
        assert assertion.passed

    def test_dlq_on_failure_passes(self) -> None:
        runner = RouteTestRunner()
        capture = _MetricCapture()
        assertion = runner._evaluate_expect(
            _ExpectStep(
                description="DLQ on ValueError",
                expectation_type=ExpectationType.DLQ_ON_FAILURE,
                error_class=ValueError,
            ),
            capture,
        )
        assert assertion.passed


class TestThenAssertion:
    """Test then() assertions (eq, truthy, in)."""

    def test_eq_pass(self) -> None:
        runner = RouteTestRunner()
        then = _ThenStep(
            description="eq 1",
            expectation_type=ExpectationType.RETURN_VALUE,
            expected=1,
            comparator="eq",
        )
        assertion = runner._evaluate_then(then, 1)
        assert assertion.passed

    def test_eq_fail(self) -> None:
        runner = RouteTestRunner()
        then = _ThenStep(
            description="eq 2",
            expectation_type=ExpectationType.RETURN_VALUE,
            expected=2,
            comparator="eq",
        )
        assertion = runner._evaluate_then(then, 1)
        assert assertion.passed is False

    def test_truthy_pass(self) -> None:
        runner = RouteTestRunner()
        then = _ThenStep(
            description="truthy",
            expectation_type=ExpectationType.RETURN_VALUE,
            expected=True,
            comparator="truthy",
        )
        assertion = runner._evaluate_then(then, "non-empty")
        assert assertion.passed

    def test_truthy_fail(self) -> None:
        runner = RouteTestRunner()
        then = _ThenStep(
            description="truthy",
            expectation_type=ExpectationType.RETURN_VALUE,
            expected=True,
            comparator="truthy",
        )
        assertion = runner._evaluate_then(then, "")
        assert assertion.passed is False

    def test_in_pass(self) -> None:
        runner = RouteTestRunner()
        then = _ThenStep(
            description="in [1,2,3]",
            expectation_type=ExpectationType.RETURN_VALUE,
            expected=[1, 2, 3],
            comparator="in",
        )
        assertion = runner._evaluate_then(then, 2)
        assert assertion.passed

    def test_in_fail(self) -> None:
        runner = RouteTestRunner()
        then = _ThenStep(
            description="in [1,2,3]",
            expectation_type=ExpectationType.RETURN_VALUE,
            expected=[1, 2, 3],
            comparator="in",
        )
        assertion = runner._evaluate_then(then, 4)
        assert assertion.passed is False


class TestThenRaisesAssertion:
    """Test exception handling в run()."""

    def test_expected_exception_passes(self) -> None:
        def fail_route(payload):
            raise ValueError("boom")

        spec = (
            RouteTest("t")
            .given("trigger failure")
            .when("call")
            .then_raises("ValueError", ValueError)
        )
        result = spec.run(fail_route)
        assert result.passed
        assert result.route_error is not None
        assert result.assertions[0].passed

    def test_unexpected_exception_fails(self) -> None:
        def fail_route(payload):
            raise KeyError("unexpected")

        spec = (
            RouteTest("t")
            .given("trigger failure")
            .when("call")
            .then_raises("ValueError", ValueError)
        )
        result = spec.run(fail_route)
        assert result.passed is False
        assert result.assertions[0].passed is False
        assert "KeyError" in result.assertions[0].actual


class TestSingleton:
    def test_singleton(self) -> None:
        r1 = get_route_test_runner()
        r2 = get_route_test_runner()
        assert r1 is r2

    def test_reset(self) -> None:
        r1 = get_route_test_runner()
        reset_route_test_runner()
        r2 = get_route_test_runner()
        assert r1 is not r2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import route_test_dsl

        assert len(route_test_dsl.__all__) == 7


class TestRealisticExample:
    """Realistic: order create route — happy path."""

    def test_order_create_happy_path(self) -> None:
        call_count = 0

        def order_create(payload):
            nonlocal call_count
            call_count += 1
            order_id = payload.get("id", "default")
            # In real code, route would record metric via runner.
            get_route_test_runner().record_metric(
                "order_create_happy", "order_created_total", 1
            )
            return {
                "status": "created",
                "order_id": order_id,
                "amount": payload.get("amount", 0),
            }

        spec = (
            RouteTest("order_create_happy")
            .given("valid order", id="o1", amount=100)
            .when("call order_create")
            .then_truthy("returns dict with status")
            .expect_metric("order_created_total", 1)
        )

        result = spec.run(order_create)
        assert result.passed
        assert call_count == 1
        assert result.route_output["status"] == "created"

    def test_payment_failure_dlq_routing(self) -> None:
        def payment_route(payload):
            if payload.get("force_fail"):
                raise ValueError("payment declined")
            return {"status": "paid"}

        runner = get_route_test_runner()

        spec = (
            RouteTest("payment_fail")
            .given("declined card", force_fail=True)
            .when("call payment")
            .then_raises("raises ValueError", ValueError)
            .expect_dlq_on_failure(ValueError)
        )

        runner.record_metric("payment_fail", "dlq_enqueued", 1)

        result = spec.run(payment_route)
        assert result.passed
        assert result.route_error is not None
