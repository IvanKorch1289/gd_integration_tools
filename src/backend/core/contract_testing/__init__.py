"""Contract Test Harness — declarative schema validation (Wave 1 P0 #7).

Проблема (EP-R1):
    Интеграции ломаются при изменении upstream API:
    - Возвращается неожиданный тип поля (int → str).
    - Добавляется новое обязательное поле.
    - Меняется формат даты.
    - Удаляется поле, на которое полагается route.

    Без contract tests эти breaking changes обнаруживаются
    только в production через инциденты.

Решение:
    ``ContractTestHarness`` + ``ContractTestCase``:

    1. ``ContractTestCase`` — declarative test spec:
       - ``input_payload`` — sample input.
       - ``expected_output_schema`` — JSON Schema (для validate).
       - ``expected_output`` — exact match (optional).
       - ``expect_error`` — True для negative tests.
       - ``setup/assert_custom`` — custom hooks.

    2. ``ContractTestHarness`` — runner:
       - ``run(test_case, route_fn)`` → ``ContractTestResult``.
       - Validates input/output against JSON Schema.
       - Reports schema violations.

    3. ``CompatibilityTest`` — backward-compat verification:
       - ``run_against_old_payload(old_payload, route_fn)`` —
         old payload should still work (or fail gracefully).

Использование::

    from src.backend.core.contract_testing import (
        ContractTestHarness, ContractTestCase,
    )

    harness = ContractTestHarness()

    test = ContractTestCase(
        name="create_order_happy_path",
        input_payload={"order_id": "o1", "amount": 100},
        expected_output_schema={
            "type": "object",
            "required": ["status", "order_id"],
        },
    )

    result = harness.run(test, my_route_fn)
    assert result.passed
"""

from __future__ import annotations

from src.backend.core.contract_testing.case import (
    CompatibilityTest,
    ContractTestCase,
    ContractTestResult,
)
from src.backend.core.contract_testing.harness import (
    ContractTestHarness,
    get_contract_test_harness,
)
from src.backend.core.contract_testing.validator import (
    SchemaValidationError,
    validate_against_schema,
)

__all__ = (
    "CompatibilityTest",
    "ContractTestCase",
    "ContractTestHarness",
    "ContractTestResult",
    "SchemaValidationError",
    "get_contract_test_harness",
    "validate_against_schema",
)
