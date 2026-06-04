"""Unit tests for banking helpers."""

# ruff: noqa: S101

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.backend.dsl.helpers.banking import (
    business_day,
    money,
    validate_bic,
    validate_iban,
    validate_inn,
    validate_kpp,
    validate_swift,
)


class TestValidateInn:
    def test_valid_inn10(self) -> None:
        assert validate_inn("7707083893") is True

    def test_valid_inn12(self) -> None:
        assert validate_inn("500100732259") is True

    def test_invalid_inn(self) -> None:
        assert validate_inn("1234567890") is False

    def test_invalid_length(self) -> None:
        assert validate_inn("123") is False


class TestValidateKpp:
    def test_valid(self) -> None:
        assert validate_kpp("773601001") is True

    def test_invalid(self) -> None:
        assert validate_kpp("123") is False


class TestValidateBic:
    def test_valid(self) -> None:
        assert validate_bic("044525225") is True

    def test_invalid(self) -> None:
        assert validate_bic("123") is False


class TestValidateSwift:
    def test_valid_8(self) -> None:
        assert validate_swift("SABRRUMM") is True

    def test_valid_11(self) -> None:
        assert validate_swift("SABRRUMMXXX") is True

    def test_invalid(self) -> None:
        assert validate_swift("abc") is False


class TestValidateIban:
    def test_valid(self) -> None:
        assert validate_iban("GB82 WEST 1234 5698 7654 32") is True

    def test_invalid(self) -> None:
        assert validate_iban("GB82INVALID") is False

    def test_empty(self) -> None:
        assert validate_iban("") is False


class TestBusinessDay:
    def test_next_day(self) -> None:
        d = date(2024, 1, 2)  # Tuesday
        assert business_day(d) == date(2024, 1, 3)

    def test_skips_weekend(self) -> None:
        d = date(2024, 1, 5)  # Friday
        assert business_day(d) == date(2024, 1, 8)  # Monday

    def test_skips_holiday(self) -> None:
        d = date(2024, 1, 2)
        holiday = date(2024, 1, 3)
        assert business_day(d, holidays=[holiday]) == date(2024, 1, 4)


class TestMoney:
    def test_from_str(self) -> None:
        assert money("10.5") == Decimal("10.50")

    def test_from_int(self) -> None:
        assert money(10) == Decimal("10.00")

    def test_from_float(self) -> None:
        assert money(10.5) == Decimal("10.50")

    def test_custom_places(self) -> None:
        assert money("10.555", places=3) == Decimal("10.555")
