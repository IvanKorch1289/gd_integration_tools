"""Route Test DSL — given/when/then declarative test spec (Wave 2 DX #27).

Проблема:
    Тесты для routes пишутся несогласованно:
    - Каждый разработчик использует свой стиль (pytest fixture, manual mock).
    - DSL-test spec отсутствует — нет шаблона для новых routes.
    - Review тестов занимает время, т.к. нет explicit given/when/then.
    - Сложно генерировать тесты из template catalog.

Решение:
    ``RouteTestDSL`` — declarative test spec с BDD-style API:

    1. ``given(...)`` — setup state, mocks, payloads.
    2. ``when(...)`` — execute route / handler.
    3. ``then(...)`` — assert expectations (result, side effects, error).
    4. ``expect_idempotency(key)`` — verify same key returns same result.
    5. ``expect_dlq_on_failure(error_class)`` — verify DLQ routing.
    6. ``expect_metric(name, value)`` — verify telemetry emission.
    7. ``expect_audit_event(type)`` — verify audit log.

Использование::

    from src.backend.core.route_test_dsl import RouteTest

    def test_order_create_happy_path():
        spec = (
            RouteTest("order_create_happy_path")
            .given("input order with valid data", payload={"order_id": "o1", "amount": 100})
            .given("mock payment service succeeds", mock_payment={"status": "ok"})
            .when("call order_create route")
            .then("returns 201 status")
            .then("returns order_id='o1'")
            .expect_metric("order_created_total", 1)
            .expect_audit_event("order.created")
        )
        result = spec.run(order_create_route)
        assert result.passed
"""

from __future__ import annotations

from src.backend.core.route_test_dsl.spec import (  # noqa: F401 — re-export
    AssertionResult,
    ExpectationType,
    RouteTest,
    RouteTestResult,
    RouteTestRunner,
    RouteTestSpec,
    get_route_test_runner,
)

__all__ = (
    "AssertionResult",
    "ExpectationType",
    "RouteTest",
    "RouteTestResult",
    "RouteTestRunner",
    "RouteTestSpec",
    "get_route_test_runner",
)
