"""Focused tests for ``core.data_quality`` (Wave 4 #35)."""

from __future__ import annotations

import pytest

from src.backend.core.data_quality import (
    DataQualityEngine,
    QualityReport,
    QualityRule,
    QualityViolation,
    RuleKind,
    RuleSet,
    get_data_quality_engine,
)
from src.backend.core.data_quality.engine import reset_data_quality_engine


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_data_quality_engine()


class TestRuleKind:
    def test_values(self) -> None:
        assert RuleKind.NON_NULL.value == "non_null"
        assert RuleKind.NON_EMPTY.value == "non_empty"
        assert RuleKind.UNIQUE.value == "unique"
        assert RuleKind.RANGE.value == "range"
        assert RuleKind.FORMAT.value == "format"
        assert RuleKind.ENUM.value == "enum"
        assert RuleKind.CUSTOM.value == "custom"


class TestQualityRule:
    def test_non_null(self) -> None:
        r = QualityRule(field="x", kind=RuleKind.NON_NULL)
        assert r.error_message == ""

    def test_range_with_bounds(self) -> None:
        r = QualityRule(field="amount", kind=RuleKind.RANGE, min=0, max=1000)
        assert r.min == 0
        assert r.max == 1000

    def test_format_with_regex(self) -> None:
        r = QualityRule(field="email", kind=RuleKind.FORMAT, regex=r"^.+@.+$")
        assert r.regex == r"^.+@.+$"

    def test_enum_with_allowed(self) -> None:
        r = QualityRule(
            field="status", kind=RuleKind.ENUM, allowed=("active", "inactive")
        )
        assert r.allowed == ("active", "inactive")


class TestRuleSet:
    def test_init(self) -> None:
        rs = RuleSet(record_type="order")
        assert rs.rules == []
        assert rs.quarantine_on_failure is True

    def test_with_rules(self) -> None:
        rs = RuleSet(
            record_type="order",
            rules=[
                QualityRule(field="id", kind=RuleKind.NON_NULL),
                QualityRule(field="amount", kind=RuleKind.RANGE, min=0),
            ],
        )
        assert len(rs.rules) == 2


class TestQualityReport:
    def test_defaults(self) -> None:
        r = QualityReport(record_type="order")
        assert r.total == 0
        assert r.passed == 0
        assert r.failed == 0
        assert r.violations == []

    def test_pass_rate_zero(self) -> None:
        r = QualityReport(record_type="x", total=0)
        assert r.pass_rate == 1.0  # default при 0.

    def test_pass_rate(self) -> None:
        r = QualityReport(record_type="x", total=10, passed=7)
        assert r.pass_rate == 0.7

    def test_to_dict(self) -> None:
        r = QualityReport(
            record_type="x",
            total=2,
            passed=1,
            failed=1,
            violations=[
                QualityViolation(
                    record_type="x",
                    field="name",
                    rule_kind=RuleKind.NON_NULL,
                    record={"name": None},
                    reason="missing",
                )
            ],
        )
        d = r.to_dict()
        assert d["record_type"] == "x"
        assert d["pass_rate"] == 0.5
        assert len(d["violations"]) == 1


class TestDataQualityEngineInit:
    def test_init(self) -> None:
        e = DataQualityEngine()
        assert e.list_record_types() == []
        assert e.quarantine_size() == 0


class TestRegister:
    def test_register(self) -> None:
        e = DataQualityEngine()
        e.register(RuleSet(record_type="order"))
        assert "order" in e.list_record_types()

    def test_register_overwrites(self) -> None:
        e = DataQualityEngine()
        rs1 = RuleSet(record_type="order")
        rs2 = RuleSet(record_type="order")
        e.register(rs1)
        e.register(rs2)
        assert e.get("order") is rs2

    def test_get_missing(self) -> None:
        e = DataQualityEngine()
        assert e.get("missing") is None


class TestCheckNonNull:
    def test_non_null_pass(self) -> None:
        e = DataQualityEngine()
        e.register(
            RuleSet(
                record_type="order",
                rules=[QualityRule(field="id", kind=RuleKind.NON_NULL)],
            )
        )
        report = e.check("order", [{"id": "o1"}])
        assert report.passed == 1
        assert report.failed == 0

    def test_non_null_fail(self) -> None:
        e = DataQualityEngine()
        e.register(
            RuleSet(
                record_type="order",
                rules=[QualityRule(field="id", kind=RuleKind.NON_NULL)],
            )
        )
        report = e.check("order", [{"id": None}])
        assert report.passed == 0
        assert report.failed == 1
        assert "id is null" in report.violations[0].reason


class TestCheckNonEmpty:
    def test_empty_string_fail(self) -> None:
        e = DataQualityEngine()
        e.register(
            RuleSet(
                record_type="x",
                rules=[QualityRule(field="name", kind=RuleKind.NON_EMPTY)],
            )
        )
        report = e.check("x", [{"name": ""}])
        assert report.failed == 1

    def test_empty_list_fail(self) -> None:
        e = DataQualityEngine()
        e.register(
            RuleSet(
                record_type="x",
                rules=[QualityRule(field="tags", kind=RuleKind.NON_EMPTY)],
            )
        )
        report = e.check("x", [{"tags": []}])
        assert report.failed == 1

    def test_non_empty_pass(self) -> None:
        e = DataQualityEngine()
        e.register(
            RuleSet(
                record_type="x",
                rules=[QualityRule(field="name", kind=RuleKind.NON_EMPTY)],
            )
        )
        report = e.check("x", [{"name": "Alice"}])
        assert report.passed == 1


class TestCheckRange:
    def test_range_pass(self) -> None:
        e = DataQualityEngine()
        e.register(
            RuleSet(
                record_type="x",
                rules=[
                    QualityRule(field="amount", kind=RuleKind.RANGE, min=0, max=100)
                ],
            )
        )
        report = e.check("x", [{"amount": 50}])
        assert report.passed == 1

    def test_range_min_fail(self) -> None:
        e = DataQualityEngine()
        e.register(
            RuleSet(
                record_type="x",
                rules=[
                    QualityRule(field="amount", kind=RuleKind.RANGE, min=0, max=100)
                ],
            )
        )
        report = e.check("x", [{"amount": -1}])
        assert report.failed == 1

    def test_range_max_fail(self) -> None:
        e = DataQualityEngine()
        e.register(
            RuleSet(
                record_type="x",
                rules=[
                    QualityRule(field="amount", kind=RuleKind.RANGE, min=0, max=100)
                ],
            )
        )
        report = e.check("x", [{"amount": 200}])
        assert report.failed == 1

    def test_range_non_numeric_fail(self) -> None:
        e = DataQualityEngine()
        e.register(
            RuleSet(
                record_type="x",
                rules=[QualityRule(field="amount", kind=RuleKind.RANGE, min=0)],
            )
        )
        report = e.check("x", [{"amount": "not-a-number"}])
        assert report.failed == 1


class TestCheckFormat:
    def test_format_email_pass(self) -> None:
        e = DataQualityEngine()
        e.register(
            RuleSet(
                record_type="user",
                rules=[
                    QualityRule(
                        field="email", kind=RuleKind.FORMAT, regex=r"^[^@]+@[^@]+$"
                    )
                ],
            )
        )
        report = e.check("user", [{"email": "alice@example.com"}])
        assert report.passed == 1

    def test_format_email_fail(self) -> None:
        e = DataQualityEngine()
        e.register(
            RuleSet(
                record_type="user",
                rules=[
                    QualityRule(
                        field="email", kind=RuleKind.FORMAT, regex=r"^[^@]+@[^@]+$"
                    )
                ],
            )
        )
        report = e.check("user", [{"email": "not-an-email"}])
        assert report.failed == 1


class TestCheckEnum:
    def test_enum_pass(self) -> None:
        e = DataQualityEngine()
        e.register(
            RuleSet(
                record_type="order",
                rules=[
                    QualityRule(
                        field="status", kind=RuleKind.ENUM, allowed=("active", "closed")
                    )
                ],
            )
        )
        report = e.check("order", [{"status": "active"}])
        assert report.passed == 1

    def test_enum_fail(self) -> None:
        e = DataQualityEngine()
        e.register(
            RuleSet(
                record_type="order",
                rules=[
                    QualityRule(
                        field="status", kind=RuleKind.ENUM, allowed=("active", "closed")
                    )
                ],
            )
        )
        report = e.check("order", [{"status": "unknown"}])
        assert report.failed == 1


class TestCheckUnique:
    def test_unique_pass(self) -> None:
        e = DataQualityEngine()
        e.register(
            RuleSet(
                record_type="x", rules=[QualityRule(field="id", kind=RuleKind.UNIQUE)]
            )
        )
        report = e.check("x", [{"id": "a"}, {"id": "b"}, {"id": "c"}])
        assert report.passed == 3

    def test_unique_fail(self) -> None:
        e = DataQualityEngine()
        e.register(
            RuleSet(
                record_type="x", rules=[QualityRule(field="id", kind=RuleKind.UNIQUE)]
            )
        )
        report = e.check("x", [{"id": "a"}, {"id": "b"}, {"id": "a"}])
        assert report.passed == 2
        assert report.failed == 1
        assert "duplicate" in report.violations[0].reason


class TestCheckCustom:
    def test_custom_pass(self) -> None:
        e = DataQualityEngine()

        def is_even(record):
            return record["n"] % 2 == 0

        e.register(
            RuleSet(
                record_type="x",
                rules=[QualityRule(field="n", kind=RuleKind.CUSTOM, custom_fn=is_even)],
            )
        )
        report = e.check("x", [{"n": 2}, {"n": 4}])
        assert report.passed == 2

    def test_custom_fail(self) -> None:
        e = DataQualityEngine()

        def is_even(record):
            return record["n"] % 2 == 0

        e.register(
            RuleSet(
                record_type="x",
                rules=[QualityRule(field="n", kind=RuleKind.CUSTOM, custom_fn=is_even)],
            )
        )
        report = e.check("x", [{"n": 2}, {"n": 3}])
        assert report.failed == 1

    def test_custom_raises(self) -> None:
        e = DataQualityEngine()

        def bad_fn(record):
            raise ValueError("boom")

        e.register(
            RuleSet(
                record_type="x",
                rules=[QualityRule(field="n", kind=RuleKind.CUSTOM, custom_fn=bad_fn)],
            )
        )
        report = e.check("x", [{"n": 1}])
        assert report.failed == 1
        assert "custom raised" in report.violations[0].reason


class TestCheckNoRuleSet:
    def test_check_without_ruleset(self) -> None:
        e = DataQualityEngine()
        report = e.check("unknown_type", [{"x": 1}])
        assert report.passed == 1
        assert report.failed == 0


class TestQuarantine:
    def test_quarantine_on_failure(self) -> None:
        e = DataQualityEngine()
        e.register(
            RuleSet(
                record_type="x", rules=[QualityRule(field="id", kind=RuleKind.NON_NULL)]
            )
        )
        e.check("x", [{"id": None}, {"id": "ok"}])
        assert e.quarantine_size() == 1
        quarantined = e.get_quarantine()
        assert quarantined[0][0] == {"id": None}

    def test_quarantine_disabled(self) -> None:
        e = DataQualityEngine()
        rs = RuleSet(
            record_type="x",
            rules=[QualityRule(field="id", kind=RuleKind.NON_NULL)],
            quarantine_on_failure=False,
        )
        e.register(rs)
        e.check("x", [{"id": None}])
        assert e.quarantine_size() == 0

    def test_manual_quarantine(self) -> None:
        e = DataQualityEngine()
        e.quarantine({"x": 1}, "manual")
        assert e.quarantine_size() == 1
        assert e.get_quarantine()[0][1] == "manual"

    def test_clear_quarantine(self) -> None:
        e = DataQualityEngine()
        e.quarantine({"x": 1}, "test")
        e.clear_quarantine()
        assert e.quarantine_size() == 0


class TestObjectRecords:
    def test_object_attribute_access(self) -> None:
        class Order:
            def __init__(self, id, amount):
                self.id = id
                self.amount = amount

        e = DataQualityEngine()
        e.register(
            RuleSet(
                record_type="order",
                rules=[QualityRule(field="id", kind=RuleKind.NON_NULL)],
            )
        )
        report = e.check("order", [Order("o1", 100), Order(None, 200)])
        assert report.passed == 1
        assert report.failed == 1


class TestSingleton:
    def test_singleton(self) -> None:
        e1 = get_data_quality_engine()
        e2 = get_data_quality_engine()
        assert e1 is e2

    def test_reset(self) -> None:
        e1 = get_data_quality_engine()
        reset_data_quality_engine()
        e2 = get_data_quality_engine()
        assert e1 is not e2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import data_quality

        assert len(data_quality.__all__) == 7


class TestRealisticExample:
    """Realistic: order validation."""

    def test_order_validation(self) -> None:
        engine = get_data_quality_engine()
        engine.register(
            RuleSet(
                record_type="order",
                rules=[
                    QualityRule(field="id", kind=RuleKind.NON_NULL),
                    QualityRule(field="id", kind=RuleKind.UNIQUE),
                    QualityRule(
                        field="amount", kind=RuleKind.RANGE, min=0, max=1_000_000
                    ),
                    QualityRule(
                        field="email", kind=RuleKind.FORMAT, regex=r"^[^@]+@[^@]+$"
                    ),
                    QualityRule(
                        field="status",
                        kind=RuleKind.ENUM,
                        allowed=("new", "paid", "shipped", "delivered"),
                    ),
                ],
            )
        )
        records = [
            {"id": "o1", "amount": 100, "email": "alice@x.com", "status": "new"},
            {
                "id": "o2",
                "amount": -5,
                "email": "bob@x.com",
                "status": "new",
            },  # bad amount
            {"id": "o1", "amount": 50, "email": "x@y.com", "status": "new"},  # dup id
            {"id": "o4", "amount": 100, "email": "bad", "status": "new"},  # bad email
            {
                "id": "o5",
                "amount": 100,
                "email": "e@x.com",
                "status": "bad",
            },  # bad enum
        ]
        report = engine.check("order", records)
        assert report.total == 5
        assert report.passed == 1
        assert report.failed == 4
        # 4 failed records quarantined.
        assert engine.quarantine_size() == 4
