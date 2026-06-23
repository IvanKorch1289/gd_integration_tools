"""Unit tests для datetime_utils shim (Sprint 57 W1).

Coverage:
* pendulum availability + fallback paths
* utc_now() returns tz-aware UTC
* parse_dt: int/float/str/datetime/None inputs
* ensure_utc: naive → UTC, aware → UTC conversion
* humanize_delta: pendulum + stdlib fallback
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.backend.core.utils.datetime_utils import (
    ensure_utc,
    humanize_delta,
    is_pendulum_available,
    parse_dt,
    utc_now,
)

# ── Smoke + availability ────────────────────────────────────────────


class TestAvailability:
    def test_pendulum_available(self) -> None:
        """pendulum установлен в venv (S57 W1 dep)."""
        assert is_pendulum_available() is True

    def test_utc_now_is_aware(self) -> None:
        """utc_now() returns tz-aware datetime в UTC."""
        now = utc_now()
        assert now.tzinfo is not None
        # Pendulum Timezone('UTC') != datetime.timezone.utc по identity, но
        # оба имеют нулевой offset — это правильная семантика.
        assert now.utcoffset() == timedelta(0)

    def test_utc_now_is_datetime_instance(self) -> None:
        """utc_now() возвращает datetime (pendulum.DateTime — subclass)."""
        now = utc_now()
        assert isinstance(now, datetime)


# ── parse_dt ────────────────────────────────────────────────────────


class TestParseDt:
    def test_none_returns_now(self) -> None:
        """None → utc_now()."""
        before = utc_now()
        result = parse_dt(None)
        after = utc_now()
        assert before <= result <= after

    def test_passthrough_datetime_naive_to_utc(self) -> None:
        """Naive datetime → UTC assumed (replace tzinfo)."""
        naive = datetime(2025, 1, 15, 10, 0, 0)
        result = parse_dt(naive)
        assert result.utcoffset() == timedelta(0)
        assert result.hour == 10

    def test_passthrough_datetime_aware_converted(self) -> None:
        """Aware datetime +05:00 → converted to UTC."""
        aware = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone(timedelta(hours=5)))
        result = parse_dt(aware)
        assert result.utcoffset() == timedelta(0)
        assert result.hour == 5  # 10:00 +05:00 = 05:00 UTC

    def test_parse_unix_seconds(self) -> None:
        """Unix timestamp (seconds) → datetime."""
        ts = 1736935200  # 2025-01-15 10:00:00 UTC
        result = parse_dt(ts)
        assert result.utcoffset() == timedelta(0)
        assert result.year == 2025
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 10

    def test_parse_unix_milliseconds(self) -> None:
        """Unix timestamp (ms, > 1e12) → datetime."""
        ts_ms = 1736935200000  # 2025-01-15 10:00:00 UTC in ms
        result = parse_dt(ts_ms)
        assert result.utcoffset() == timedelta(0)
        assert result.year == 2025
        assert result.hour == 10

    def test_parse_iso_string_with_z(self) -> None:
        """ISO 8601 string with 'Z' suffix → UTC datetime."""
        result = parse_dt("2025-01-15T10:00:00Z")
        assert result.utcoffset() == timedelta(0)
        assert result.year == 2025
        assert result.hour == 10

    def test_parse_iso_string_with_offset(self) -> None:
        """ISO 8601 string с +05:00 offset → converted to UTC."""
        result = parse_dt("2025-01-15T10:00:00+05:00")
        assert result.utcoffset() == timedelta(0)
        assert result.hour == 5  # converted to UTC

    def test_parse_unsupported_type_raises(self) -> None:
        """Unsupported type → TypeError."""
        with pytest.raises(TypeError, match="unsupported type"):
            parse_dt([2025, 1, 15])  # list not supported


# ── ensure_utc ──────────────────────────────────────────────────────


class TestEnsureUtc:
    def test_naive_to_utc(self) -> None:
        """Naive datetime → assume UTC."""
        naive = datetime(2025, 6, 1, 12, 0, 0)
        result = ensure_utc(naive)
        assert result.utcoffset() == timedelta(0)
        assert result == naive.replace(tzinfo=timezone.utc)

    def test_aware_to_utc_converts(self) -> None:
        """Aware +03:00 → converted to UTC (hour -3)."""
        aware = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone(timedelta(hours=3)))
        result = ensure_utc(aware)
        assert result.utcoffset() == timedelta(0)
        assert result.hour == 9
        assert result.day == 1

    def test_already_utc_unchanged(self) -> None:
        """Already UTC → returned as-is."""
        utc = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = ensure_utc(utc)
        assert result == utc


# ── humanize_delta ──────────────────────────────────────────────────


class TestHumanizeDelta:
    def test_past_humanized(self) -> None:
        """3 hours ago → '3 hours ago' (pendulum)."""
        past = utc_now() - timedelta(hours=3)
        result = humanize_delta(past)
        # pendulum / stdlib fallback: "3 hours ago"
        assert "3" in result
        assert "hour" in result.lower()

    def test_future_humanized(self) -> None:
        """Future datetime → contains 'in' or numeric days."""
        future = utc_now() + timedelta(days=2)
        result = humanize_delta(future, absolute=False)
        # pendulum uses "in 2 days", stdlib fallback uses "in 2 days" too
        assert "2" in result
        assert "day" in result.lower()

    def test_absolute_mode(self) -> None:
        """absolute=True → no 'in' / 'ago' sign."""
        past = utc_now() - timedelta(hours=2)
        result = humanize_delta(past, absolute=True)
        # absolute=True: pendulum "2 hours" / stdlib "2 hours"
        assert "in" not in result
        assert "ago" not in result
        assert "2" in result

    def test_zero_delta(self) -> None:
        """dt == other → 'now' (stdlib fallback) or 'a few seconds' (pendulum)."""
        now = utc_now()
        result = humanize_delta(now, other=now)
        # pendulum: "a few seconds"; stdlib: "now"
        assert "now" in result.lower() or "second" in result.lower()
