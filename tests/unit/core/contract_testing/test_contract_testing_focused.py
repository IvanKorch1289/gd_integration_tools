"""Focused tests for ``core.contract_testing`` (Wave 1 P0 #7)."""

from __future__ import annotations

import asyncio

import pytest

from src.backend.core.contract_testing import (
    CompatibilityTest,
    ContractTestCase,
    ContractTestHarness,
    ContractTestResult,
    SchemaValidationError,
    get_contract_test_harness,
    validate_against_schema,
)
from src.backend.core.contract_testing.harness import reset_contract_test_harness


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_contract_test_harness()


class TestSchemaValidator:
    """``validate_against_schema()`` — JSON Schema subset."""

    def test_type_string_valid(self) -> None:
        errors = validate_against_schema("hello", {"type": "string"})
        assert errors == []

    def test_type_string_invalid(self) -> None:
        errors = validate_against_schema(42, {"type": "string"})
        assert len(errors) == 1
        assert "string" in errors[0]

    def test_type_integer(self) -> None:
        errors = validate_against_schema(42, {"type": "integer"})
        assert errors == []

    def test_type_integer_rejects_bool(self) -> None:
        """bool не считается integer."""
        errors = validate_against_schema(True, {"type": "integer"})
        assert len(errors) == 1

    def test_type_number_accepts_float(self) -> None:
        errors = validate_against_schema(3.14, {"type": "number"})
        assert errors == []

    def test_type_boolean(self) -> None:
        assert validate_against_schema(True, {"type": "boolean"}) == []
        assert validate_against_schema(False, {"type": "boolean"}) == []

    def test_type_array(self) -> None:
        errors = validate_against_schema([1, 2, 3], {"type": "array"})
        assert errors == []

    def test_type_object(self) -> None:
        errors = validate_against_schema({"a": 1}, {"type": "object"})
        assert errors == []

    def test_type_null(self) -> None:
        errors = validate_against_schema(None, {"type": "null"})
        assert errors == []

    def test_required_missing(self) -> None:
        schema = {"type": "object", "required": ["name"]}
        errors = validate_against_schema({}, schema)
        assert any("name" in e and "required" in e for e in errors)

    def test_required_present(self) -> None:
        schema = {"type": "object", "required": ["name"]}
        errors = validate_against_schema({"name": "x"}, schema)
        assert errors == []

    def test_properties_type_check(self) -> None:
        schema = {
            "type": "object",
            "properties": {"age": {"type": "integer"}},
        }
        assert validate_against_schema({"age": 30}, schema) == []
        assert len(validate_against_schema({"age": "30"}, schema)) == 1

    def test_enum_valid(self) -> None:
        schema = {"enum": ["red", "green", "blue"]}
        assert validate_against_schema("red", schema) == []

    def test_enum_invalid(self) -> None:
        schema = {"enum": ["red", "green", "blue"]}
        errors = validate_against_schema("yellow", schema)
        assert len(errors) == 1

    def test_minimum(self) -> None:
        assert validate_against_schema(5, {"type": "integer", "minimum": 0}) == []
        assert len(validate_against_schema(-1, {"type": "integer", "minimum": 0})) == 1

    def test_maximum(self) -> None:
        assert validate_against_schema(5, {"type": "integer", "maximum": 10}) == []
        assert len(validate_against_schema(11, {"type": "integer", "maximum": 10})) == 1

    def test_minLength(self) -> None:
        assert validate_against_schema("ab", {"type": "string", "minLength": 2}) == []
        assert len(validate_against_schema("a", {"type": "string", "minLength": 2})) == 1

    def test_maxLength(self) -> None:
        assert validate_against_schema("abc", {"type": "string", "maxLength": 5}) == []
        assert len(validate_against_schema("abcdef", {"type": "string", "maxLength": 5})) == 1

    def test_pattern(self) -> None:
        assert validate_against_schema(
            "abc123", {"type": "string", "pattern": r"^[a-z0-9]+$"}
        ) == []
        assert len(
            validate_against_schema(
                "ABC", {"type": "string", "pattern": r"^[a-z0-9]+$"}
            )
        ) == 1

    def test_array_items(self) -> None:
        schema = {"type": "array", "items": {"type": "integer"}}
        assert validate_against_schema([1, 2, 3], schema) == []
        errors = validate_against_schema([1, "2", 3], schema)
        assert len(errors) == 1

    def test_nested_object(self) -> None:
        schema = {
            "type": "object",
            "required": ["user"],
            "properties": {
                "user": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {"id": {"type": "string"}},
                },
            },
        }
        assert validate_against_schema({"user": {"id": "u1"}}, schema) == []
        errors = validate_against_schema({"user": {}}, schema)
        assert any("user.id" in e for e in errors)

    def test_multiple_errors(self) -> None:
        schema = {"type": "object", "required": ["a", "b"]}
        errors = validate_against_schema({"a": 1}, schema)
        assert len(errors) == 1  # только b missing


class TestContractTestCase:
    def test_defaults(self) -> None:
        c = ContractTestCase(name="t1")
        assert c.input_payload is None
        assert c.expected_output_schema == {}
        assert c.expected_output is None
        assert c.expect_error is False
        assert c.error_type is None
        assert c.tags == []

    def test_full(self) -> None:
        c = ContractTestCase(
            name="t1",
            input_payload={"x": 1},
            expected_output_schema={"type": "object"},
            expected_output={"status": "ok"},
            expect_error=False,
            tags=["smoke"],
        )
        assert c.input_payload == {"x": 1}
        assert c.tags == ["smoke"]


class TestContractTestResult:
    def test_defaults(self) -> None:
        r = ContractTestResult(test_name="t1", passed=True)
        assert r.schema_errors == []
        assert r.output_mismatch is False
        assert r.expected_error is False
        assert r.actual_error is None
        assert r.duration_ms == 0.0


class TestCompatibilityTest:
    def test_defaults(self) -> None:
        c = CompatibilityTest(name="compat")
        assert c.old_payload is None
        assert c.new_payload is None
        assert c.contract_version == "1.0"


class TestContractTestHarnessInit:
    def test_init(self) -> None:
        h = ContractTestHarness()
        assert h.history == []


class TestHarnessRun:
    def test_sync_route_pass(self) -> None:
        h = ContractTestHarness()

        def route(payload):
            return {"status": "ok", "echo": payload}

        tc = ContractTestCase(
            name="t1",
            input_payload={"x": 1},
            expected_output_schema={
                "type": "object",
                "required": ["status"],
            },
        )
        result = h.run(tc, route)
        assert result.passed is True
        assert result.schema_errors == []

    def test_sync_route_schema_failure(self) -> None:
        h = ContractTestHarness()

        def route(payload):
            return {"foo": "bar"}  # missing required "status"

        tc = ContractTestCase(
            name="t1",
            input_payload={},
            expected_output_schema={
                "type": "object",
                "required": ["status"],
            },
        )
        result = h.run(tc, route)
        assert result.passed is False
        assert len(result.schema_errors) >= 1

    def test_sync_route_expected_output_match(self) -> None:
        h = ContractTestHarness()

        def route(payload):
            return {"id": "abc"}

        tc = ContractTestCase(
            name="t1",
            expected_output={"id": "abc"},
        )
        result = h.run(tc, route)
        assert result.passed is True

    def test_sync_route_output_mismatch(self) -> None:
        h = ContractTestHarness()

        def route(payload):
            return {"id": "xyz"}

        tc = ContractTestCase(
            name="t1",
            expected_output={"id": "abc"},
        )
        result = h.run(tc, route)
        assert result.passed is False
        assert result.output_mismatch is True

    def test_negative_test_expected_error(self) -> None:
        h = ContractTestHarness()

        def route(payload):
            raise ValueError("bad input")

        tc = ContractTestCase(
            name="t1",
            expect_error=True,
            error_type=ValueError,
        )
        result = h.run(tc, route)
        assert result.passed is True
        assert result.expected_error is True

    def test_negative_test_wrong_error_type(self) -> None:
        h = ContractTestHarness()

        def route(payload):
            raise ValueError("bad")

        tc = ContractTestCase(
            name="t1",
            expect_error=True,
            error_type=KeyError,  # wrong
        )
        result = h.run(tc, route)
        assert result.passed is False

    def test_unexpected_error(self) -> None:
        h = ContractTestHarness()

        def route(payload):
            raise RuntimeError("boom")

        tc = ContractTestCase(name="t1")
        result = h.run(tc, route)
        assert result.passed is False
        assert "RuntimeError" in result.actual_error

    async def test_async_route(self) -> None:
        h = ContractTestHarness()

        async def route(payload):
            return {"status": "ok", "echo": payload}

        tc = ContractTestCase(
            name="t1",
            input_payload={"x": 1},
            expected_output_schema={"type": "object", "required": ["status"]},
        )
        # Async coroutines are awaited via asyncio.run.
        result = h.run(tc, route)
        assert result.passed is True


class TestRunSuite:
    def test_run_multiple(self) -> None:
        h = ContractTestHarness()

        def route(payload):
            return {"status": "ok"}

        cases = [
            ContractTestCase(
                name=f"t{i}",
                expected_output_schema={"type": "object", "required": ["status"]},
            )
            for i in range(3)
        ]
        results = h.run_suite(cases, route)
        assert len(results) == 3
        assert all(r.passed for r in results)


class TestRunCompatibility:
    def test_compat_passing(self) -> None:
        h = ContractTestHarness()

        def route(payload):
            return {"result": "ok"}

        compat = CompatibilityTest(
            name="order_create",
            old_payload={"order_id": "o1"},
            new_payload={"order_id": "o1", "amount": 100},
            contract_version="1.0",
        )
        result = h.run_compatibility(compat, route)
        assert result.passed is True


class TestHarnessHistory:
    def test_history(self) -> None:
        h = ContractTestHarness()

        def route(payload):
            return {}

        h.run(ContractTestCase(name="t1"), route)
        h.run(ContractTestCase(name="t2"), route)
        assert len(h.history) == 2
        h.clear_history()
        assert len(h.history) == 0


class TestSingleton:
    def test_singleton(self) -> None:
        h1 = get_contract_test_harness()
        h2 = get_contract_test_harness()
        assert h1 is h2

    def test_reset(self) -> None:
        h1 = get_contract_test_harness()
        reset_contract_test_harness()
        h2 = get_contract_test_harness()
        assert h1 is not h2


class TestSchemaValidationError:
    def test_init(self) -> None:
        err = SchemaValidationError("$.x", "missing field")
        assert err.path == "$.x"
        assert "$.x" in str(err)
        assert "missing field" in str(err)


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import contract_testing

        assert len(contract_testing.__all__) == 7


class TestRealisticExample:
    def test_order_route_contract(self) -> None:
        """Realistic example: order create route contract."""
        h = get_contract_test_harness()

        def create_order(payload):
            if "order_id" not in payload:
                raise ValueError("missing order_id")
            return {"status": "created", "order_id": payload["order_id"]}

        # Happy path.
        happy = ContractTestCase(
            name="create_order_happy",
            input_payload={"order_id": "o1", "amount": 100},
            expected_output_schema={
                "type": "object",
                "required": ["status", "order_id"],
                "properties": {
                    "status": {"type": "string", "enum": ["created"]},
                    "order_id": {"type": "string"},
                },
            },
        )

        # Negative — missing field.
        negative = ContractTestCase(
            name="create_order_missing_id",
            input_payload={"amount": 100},
            expect_error=True,
            error_type=ValueError,
        )

        results = h.run_suite([happy, negative], create_order)
        assert all(r.passed for r in results)
        assert len(h.history) == 2
