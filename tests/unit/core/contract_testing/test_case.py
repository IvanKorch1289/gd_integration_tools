"""Tests for ``src.backend.core.contract_testing.case``.

Wave 1 P0 #7: ContractTestCase, ContractTestResult, CompatibilityTest DTO.
"""

from __future__ import annotations

from src.backend.core.contract_testing import case as mod
from src.backend.core.contract_testing.case import (
    CompatibilityTest,
    ContractTestCase,
    ContractTestResult,
)


class TestContractTestCaseDefaults:
    """Defaults конструктора."""

    def test_minimal_construction_with_only_name(self) -> None:
        c = ContractTestCase(name="t1")
        assert c.name == "t1"

    def test_default_input_payload_is_none(self) -> None:
        c = ContractTestCase(name="t1")
        assert c.input_payload is None

    def test_default_schema_is_empty_dict(self) -> None:
        c = ContractTestCase(name="t1")
        assert c.expected_output_schema == {}

    def test_default_expected_output_is_none(self) -> None:
        c = ContractTestCase(name="t1")
        assert c.expected_output is None

    def test_default_expect_error_false(self) -> None:
        c = ContractTestCase(name="t1")
        assert c.expect_error is False

    def test_default_error_type_is_none(self) -> None:
        c = ContractTestCase(name="t1")
        assert c.error_type is None

    def test_default_tags_is_empty_list(self) -> None:
        c = ContractTestCase(name="t1")
        assert c.tags == []
        assert isinstance(c.tags, list)


class TestContractTestCaseExplicit:
    """Явные значения."""

    def test_input_payload(self) -> None:
        payload = {"foo": "bar", "n": 42}
        c = ContractTestCase(name="t1", input_payload=payload)
        assert c.input_payload == payload

    def test_expected_output_schema(self) -> None:
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        c = ContractTestCase(name="t1", expected_output_schema=schema)
        assert c.expected_output_schema == schema

    def test_expected_output(self) -> None:
        out = {"answer": 42}
        c = ContractTestCase(name="t1", expected_output=out)
        assert c.expected_output == out

    def test_expect_error_true(self) -> None:
        c = ContractTestCase(name="t1", expect_error=True)
        assert c.expect_error is True

    def test_error_type_set(self) -> None:
        c = ContractTestCase(name="t1", error_type=ValueError)
        assert c.error_type is ValueError

    def test_tags_list(self) -> None:
        c = ContractTestCase(name="t1", tags=["smoke", "critical"])
        assert c.tags == ["smoke", "critical"]


class TestContractTestResultDefaults:
    """Defaults ContractTestResult."""

    def test_minimal(self) -> None:
        r = ContractTestResult(test_name="t1", passed=True)
        assert r.test_name == "t1"
        assert r.passed is True

    def test_default_schema_errors_empty(self) -> None:
        r = ContractTestResult(test_name="t1", passed=True)
        assert r.schema_errors == []
        assert isinstance(r.schema_errors, list)

    def test_default_output_mismatch_false(self) -> None:
        r = ContractTestResult(test_name="t1", passed=True)
        assert r.output_mismatch is False

    def test_default_expected_error_false(self) -> None:
        r = ContractTestResult(test_name="t1", passed=True)
        assert r.expected_error is False

    def test_default_actual_error_none(self) -> None:
        r = ContractTestResult(test_name="t1", passed=True)
        assert r.actual_error is None

    def test_default_duration_ms_zero(self) -> None:
        r = ContractTestResult(test_name="t1", passed=True)
        assert r.duration_ms == 0.0


class TestContractTestResultExplicit:
    """Явные значения."""

    def test_failed(self) -> None:
        r = ContractTestResult(test_name="t1", passed=False)
        assert r.passed is False

    def test_schema_errors(self) -> None:
        r = ContractTestResult(
            test_name="t1", passed=False, schema_errors=["missing x", "wrong type"]
        )
        assert r.schema_errors == ["missing x", "wrong type"]

    def test_output_mismatch_true(self) -> None:
        r = ContractTestResult(
            test_name="t1", passed=False, output_mismatch=True
        )
        assert r.output_mismatch is True

    def test_expected_error_and_actual_error(self) -> None:
        r = ContractTestResult(
            test_name="t1",
            passed=True,
            expected_error=True,
            actual_error="ValueError: bad input",
        )
        assert r.expected_error is True
        assert r.actual_error == "ValueError: bad input"

    def test_duration_ms(self) -> None:
        r = ContractTestResult(test_name="t1", passed=True, duration_ms=123.45)
        assert r.duration_ms == 123.45


class TestCompatibilityTestDefaults:
    """Defaults CompatibilityTest."""

    def test_minimal_with_name(self) -> None:
        c = CompatibilityTest(name="compat1")
        assert c.name == "compat1"

    def test_default_old_payload_none(self) -> None:
        c = CompatibilityTest(name="c1")
        assert c.old_payload is None

    def test_default_new_payload_none(self) -> None:
        c = CompatibilityTest(name="c1")
        assert c.new_payload is None

    def test_default_contract_version(self) -> None:
        c = CompatibilityTest(name="c1")
        assert c.contract_version == "1.0"


class TestCompatibilityTestExplicit:
    """Явные значения CompatibilityTest."""

    def test_old_payload(self) -> None:
        old = {"legacy": "v1"}
        c = CompatibilityTest(name="c1", old_payload=old)
        assert c.old_payload == old

    def test_new_payload(self) -> None:
        new = {"modern": "v2"}
        c = CompatibilityTest(name="c1", new_payload=new)
        assert c.new_payload == new

    def test_custom_contract_version(self) -> None:
        c = CompatibilityTest(name="c1", contract_version="2.5")
        assert c.contract_version == "2.5"

    def test_all_fields(self) -> None:
        c = CompatibilityTest(
            name="c1",
            old_payload={"x": 1},
            new_payload={"x": 2},
            contract_version="2.0",
        )
        assert c.name == "c1"
        assert c.old_payload == {"x": 1}
        assert c.new_payload == {"x": 2}
        assert c.contract_version == "2.0"


class TestAllExports:
    """Проверка __all__."""

    def test_all_contains_three_classes(self) -> None:
        assert "ContractTestCase" in mod.__all__
        assert "ContractTestResult" in mod.__all__
        assert "CompatibilityTest" in mod.__all__
        assert len(mod.__all__) == 3


class TestEquality:
    """dataclass eq — структурное равенство."""

    def test_case_equal_when_same(self) -> None:
        a = ContractTestCase(name="t1", tags=["x"])
        b = ContractTestCase(name="t1", tags=["x"])
        assert a == b

    def test_case_not_equal_different_name(self) -> None:
        a = ContractTestCase(name="t1")
        b = ContractTestCase(name="t2")
        assert a != b

    def test_result_equal(self) -> None:
        a = ContractTestResult(test_name="t1", passed=True)
        b = ContractTestResult(test_name="t1", passed=True)
        assert a == b

    def test_compat_equal(self) -> None:
        a = CompatibilityTest(name="c1", contract_version="1.0")
        b = CompatibilityTest(name="c1", contract_version="1.0")
        assert a == b


class TestRepr:
    """dataclass имеет стабильный repr."""

    def test_case_repr_contains_class_name(self) -> None:
        c = ContractTestCase(name="t1")
        assert "ContractTestCase" in repr(c)

    def test_result_repr_contains_class_name(self) -> None:
        r = ContractTestResult(test_name="t1", passed=True)
        assert "ContractTestResult" in repr(r)

    def test_compat_repr_contains_class_name(self) -> None:
        c = CompatibilityTest(name="c1")
        assert "CompatibilityTest" in repr(c)


class TestDataclassSlots:
    """slots=True — smoke-проверка."""

    def test_case_has_slots(self) -> None:
        c = ContractTestCase(name="t1")
        # Объявленные поля присутствуют
        assert hasattr(c, "name")
        assert hasattr(c, "tags")

    def test_result_has_slots(self) -> None:
        r = ContractTestResult(test_name="t1", passed=True)
        assert hasattr(r, "test_name")
        assert hasattr(r, "duration_ms")

    def test_compat_has_slots(self) -> None:
        c = CompatibilityTest(name="c1")
        assert hasattr(c, "name")
        assert hasattr(c, "contract_version")


class TestTagsIndependent:
    """default_factory=list — каждый instance имеет свой list."""

    def test_tags_independent_per_instance(self) -> None:
        a = ContractTestCase(name="t1")
        b = ContractTestCase(name="t2")
        a.tags.append("foo")
        assert b.tags == []

    def test_schema_errors_independent(self) -> None:
        a = ContractTestResult(test_name="t1", passed=True)
        b = ContractTestResult(test_name="t2", passed=True)
        a.schema_errors.append("err")
        assert b.schema_errors == []