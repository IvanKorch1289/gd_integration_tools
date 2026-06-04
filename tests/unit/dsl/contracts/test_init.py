"""Tests for dsl/contracts expectation validators."""

from __future__ import annotations

from src.backend.dsl.contracts import Expectation, check_expectations


class TestExpectation:
    def test_not_null(self) -> None:
        e = Expectation(column="name", not_null=True)
        result = e.check([{"name": "Alice"}, {"name": None}])
        assert result.passed is False
        assert result.failed_rows == 1

    def test_unique(self) -> None:
        e = Expectation(column="id", unique=True)
        result = e.check([{"id": 1}, {"id": 2}, {"id": 1}])
        assert result.passed is False
        assert result.failed_rows == 1

    def test_regex(self) -> None:
        e = Expectation(column="email", regex=r"@")
        result = e.check([{"email": "a@b.com"}, {"email": "bad"}])
        assert result.passed is False
        assert result.failed_rows == 1

    def test_range(self) -> None:
        e = Expectation(column="age", range=(0, 120))
        result = e.check([{"age": 25}, {"age": 200}])
        assert result.passed is False
        assert result.failed_rows == 1

    def test_range_non_numeric(self) -> None:
        e = Expectation(column="age", range=(0, 120))
        result = e.check([{"age": "twenty"}])
        assert result.passed is False
        assert result.failed_rows == 1

    def test_all_pass(self) -> None:
        e = Expectation(column="name", not_null=True, unique=True)
        result = e.check([{"name": "A"}, {"name": "B"}])
        assert result.passed is True
        assert result.failed_rows == 0

    def test_none_value_skips_checks(self) -> None:
        e = Expectation(column="x", regex=r"\d+", range=(0, 10))
        result = e.check([{"x": None}])
        assert result.passed is True


class TestCheckExpectations:
    def test_multiple(self) -> None:
        e1 = Expectation(column="a", not_null=True)
        e2 = Expectation(column="b", unique=True)
        results = check_expectations([e1, e2], [{"a": 1, "b": 1}, {"a": None, "b": 2}])
        assert len(results) == 2
        assert results[0].passed is False
        assert results[1].passed is True
