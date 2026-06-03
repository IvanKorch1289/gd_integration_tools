"""Tests for dsl/helpers/datetime_utils.py."""

from __future__ import annotations

from datetime import datetime, timezone

from src.backend.dsl.helpers.datetime_utils import add_days, now, to_iso8601


class TestNow:
    def test_utc_default(self) -> None:
        dt = now()
        assert dt.tzinfo is timezone.utc

    def test_with_timezone(self) -> None:
        dt = now("Europe/Moscow")
        assert dt.tzinfo is not None
        assert dt.tzinfo.utcoffset(dt) is not None


class TestAddDays:
    def test_add_positive(self) -> None:
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        result = add_days(base, 5)
        assert result == datetime(2024, 1, 6, tzinfo=timezone.utc)

    def test_add_negative(self) -> None:
        base = datetime(2024, 1, 10, tzinfo=timezone.utc)
        result = add_days(base, -3)
        assert result == datetime(2024, 1, 7, tzinfo=timezone.utc)


class TestToIso8601:
    def test_format(self) -> None:
        dt = datetime(2024, 6, 15, 12, 30, 45, tzinfo=timezone.utc)
        assert to_iso8601(dt) == "2024-06-15T12:30:45+00:00"
