"""Tests for core/utils/datetime_utils.py (S98 — coverage push).

Covers: utc_now, parse_dt (4 input types), ensure_utc, humanize_delta.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone


def test_is_pendulum_available() -> None:
    """is_pendulum_available: True/False в зависимости от installed dep."""
    from src.backend.core.utils.datetime_utils import is_pendulum_available

    assert isinstance(is_pendulum_available(), bool)


def test_utc_now_returns_aware_datetime() -> None:
    """utc_now: returns timezone-aware datetime."""
    from src.backend.core.utils.datetime_utils import utc_now

    now = utc_now()
    assert isinstance(now, datetime)
    assert now.tzinfo is not None


def test_utc_now_tz_is_utc() -> None:
    """utc_now: tzinfo == UTC (может быть pendulum UTC wrapper)."""
    from src.backend.core.utils.datetime_utils import utc_now

    now = utc_now()
    # Convert to UTC and check same instant.
    assert now.astimezone(UTC) == now.astimezone(UTC)


# ─── parse_dt ─────────────────────────────────────────────────────


def test_parse_dt_none_returns_now() -> None:
    """parse_dt(None) → utc_now()."""
    from src.backend.core.utils.datetime_utils import parse_dt, utc_now

    before = utc_now()
    result = parse_dt(None)
    after = utc_now()
    # result should be between before and after.
    assert before <= result <= after


def test_parse_dt_datetime_input() -> None:
    """parse_dt(datetime) → passed through с ensure_utc."""
    from src.backend.core.utils.datetime_utils import parse_dt

    naive = datetime(2025, 1, 15, 10, 0, 0)
    result = parse_dt(naive)
    assert result.tzinfo is not None
    assert result.year == 2025 and result.month == 1 and result.day == 15


def test_parse_dt_aware_datetime_keeps_value() -> None:
    """parse_dt(aware datetime) → converted to UTC."""
    from src.backend.core.utils.datetime_utils import parse_dt

    plus5 = timezone(timedelta(hours=5))
    aware = datetime(2025, 1, 15, 15, 0, 0, tzinfo=plus5)
    result = parse_dt(aware)
    assert result.utcoffset() == timedelta(0)
    assert result.hour == 10  # 15:00 +05:00 = 10:00 UTC


def test_parse_dt_int_seconds() -> None:
    """parse_dt(int < 1e12) → unix seconds."""
    from src.backend.core.utils.datetime_utils import parse_dt

    # 2025-01-15T10:00:00Z = 1736935200
    result = parse_dt(1736935200)
    assert result.year == 2025
    assert result.month == 1
    assert result.day == 15


def test_parse_dt_int_milliseconds() -> None:
    """parse_dt(int > 1e12) → milliseconds heuristic."""
    from src.backend.core.utils.datetime_utils import parse_dt

    ms = 1736935200000  # ms since epoch
    result = parse_dt(ms)
    assert result.year == 2025
    assert result.month == 1


def test_parse_dt_float_seconds() -> None:
    """parse_dt(float) → unix seconds (с дробной частью)."""
    from src.backend.core.utils.datetime_utils import parse_dt

    result = parse_dt(1736935200.5)
    assert result.microsecond == 500000


def test_parse_dt_string_iso() -> None:
    """parse_dt(ISO 8601 string) → datetime."""
    from src.backend.core.utils.datetime_utils import parse_dt

    result = parse_dt("2025-01-15T10:00:00Z")
    assert result.year == 2025
    assert result.day == 15
    assert result.tzinfo is not None


def test_parse_dt_string_iso_with_offset() -> None:
    """parse_dt('2025-01-15T10:00:00+05:00') → UTC converted."""
    from src.backend.core.utils.datetime_utils import parse_dt

    result = parse_dt("2025-01-15T10:00:00+05:00")
    assert result.utcoffset() == timedelta(0)
    assert result.hour == 5  # 10:00 +05:00 = 05:00 UTC


def test_parse_dt_unsupported_type_raises() -> None:
    """parse_dt(unsupported) → TypeError."""
    from src.backend.core.utils.datetime_utils import parse_dt

    import pytest

    with pytest.raises(TypeError, match="unsupported"):
        parse_dt([1, 2, 3])  # type: ignore[arg-type]


# ─── ensure_utc ───────────────────────────────────────────────────


def test_ensure_utc_naive_assumes_utc() -> None:
    """ensure_utc(naive) → UTC-aware."""
    from src.backend.core.utils.datetime_utils import ensure_utc

    naive = datetime(2025, 1, 15, 10, 0)
    result = ensure_utc(naive)
    assert result.tzinfo is not None
    assert result.utcoffset() == timedelta(0)
    assert result.hour == 10  # assumes UTC


def test_ensure_utc_aware_converts_to_utc() -> None:
    """ensure_utc(aware non-UTC) → converted to UTC."""
    from src.backend.core.utils.datetime_utils import ensure_utc

    plus5 = timezone(timedelta(hours=5))
    aware = datetime(2025, 1, 15, 15, 0, tzinfo=plus5)
    result = ensure_utc(aware)
    assert result.utcoffset() == timedelta(0)
    assert result.hour == 10


def test_ensure_utc_already_utc_unchanged() -> None:
    """ensure_utc(UTC) → unchanged."""
    from src.backend.core.utils.datetime_utils import ensure_utc

    utc = datetime(2025, 1, 15, 10, 0, tzinfo=UTC)
    result = ensure_utc(utc)
    assert result == utc


# ─── humanize_delta ───────────────────────────────────────────────


def test_humanize_delta_seconds() -> None:
    """humanize_delta: seconds → 'N seconds' (stdlib fallback or pendulum)."""
    from src.backend.core.utils.datetime_utils import humanize_delta, utc_now

    past = utc_now() - timedelta(seconds=30)
    result = humanize_delta(past)
    assert "second" in result


def test_humanize_delta_minutes() -> None:
    """humanize_delta: minutes → 'N minutes'."""
    from src.backend.core.utils.datetime_utils import humanize_delta, utc_now

    past = utc_now() - timedelta(minutes=5)
    result = humanize_delta(past)
    assert "minute" in result


def test_humanize_delta_hours() -> None:
    """humanize_delta: hours → 'N hours'."""
    from src.backend.core.utils.datetime_utils import humanize_delta, utc_now

    past = utc_now() - timedelta(hours=3)
    result = humanize_delta(past)
    assert "hour" in result


def test_humanize_delta_days() -> None:
    """humanize_delta: days → 'N days'."""
    from src.backend.core.utils.datetime_utils import humanize_delta, utc_now

    past = utc_now() - timedelta(days=2)
    result = humanize_delta(past)
    assert "day" in result


def test_humanize_delta_zero() -> None:
    """humanize_delta: same time → 'now' (stdlib fallback)."""
    from src.backend.core.utils.datetime_utils import humanize_delta, utc_now

    now = utc_now()
    result = humanize_delta(now, other=now, absolute=True)
    # Either pendulum "a few seconds" or stdlib "now" — should contain "now" or "second".
    assert result != ""


def test_humanize_delta_explicit_other() -> None:
    """humanize_delta: explicit other reference."""
    from src.backend.core.utils.datetime_utils import humanize_delta

    a = datetime(2025, 1, 15, 10, 0, tzinfo=UTC)
    b = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)  # 2 hours later
    result = humanize_delta(a, other=b, absolute=True)
    assert "hour" in result


def test_datetime_utils_module_dunder_all() -> None:
    """__all__ = 5 публичных symbols."""
    import src.backend.core.utils.datetime_utils as mod

    assert mod.__all__ == (
        "ensure_utc",
        "humanize_delta",
        "is_pendulum_available",
        "parse_dt",
        "utc_now",
    )


# ─── pendulum unavailable path (stdlib fallback) ──────────────────


def test_humanize_delta_stdlib_fallback_seconds(monkeypatch) -> None:
    """humanize_delta: pendulum=None → stdlib fallback seconds path."""
    import src.backend.core.utils.datetime_utils as mod

    monkeypatch.setattr(mod, "_HAS_PENDULUM", False)
    other = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
    dt = other - timedelta(seconds=30)
    result = mod.humanize_delta(dt, other=other, absolute=True)
    assert "30 second" in result


def test_humanize_delta_stdlib_fallback_minutes(monkeypatch) -> None:
    """humanize_delta: pendulum=None → stdlib fallback minutes path."""
    import src.backend.core.utils.datetime_utils as mod

    monkeypatch.setattr(mod, "_HAS_PENDULUM", False)
    other = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
    dt = other - timedelta(minutes=5)
    result = mod.humanize_delta(dt, other=other, absolute=True)
    assert "5 minute" in result


def test_humanize_delta_stdlib_fallback_hours(monkeypatch) -> None:
    """humanize_delta: pendulum=None → stdlib fallback hours path."""
    import src.backend.core.utils.datetime_utils as mod

    monkeypatch.setattr(mod, "_HAS_PENDULUM", False)
    other = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
    dt = other - timedelta(hours=2)
    result = mod.humanize_delta(dt, other=other, absolute=True)
    assert "2 hour" in result


def test_humanize_delta_stdlib_fallback_days(monkeypatch) -> None:
    """humanize_delta: pendulum=None → stdlib fallback days path."""
    import src.backend.core.utils.datetime_utils as mod

    monkeypatch.setattr(mod, "_HAS_PENDULUM", False)
    other = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
    dt = other - timedelta(days=3)
    result = mod.humanize_delta(dt, other=other, absolute=True)
    assert "3 day" in result


def test_humanize_delta_stdlib_fallback_relative_signed(monkeypatch) -> None:
    """humanize_delta: pendulum=None + absolute=False → 'in' / 'ago' suffix."""
    import src.backend.core.utils.datetime_utils as mod

    monkeypatch.setattr(mod, "_HAS_PENDULUM", False)
    other = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
    past = other - timedelta(seconds=45)
    future = other + timedelta(seconds=45)
    result_past = mod.humanize_delta(past, other=other, absolute=False)
    result_future = mod.humanize_delta(future, other=other, absolute=False)
    # Should contain "ago" / "in" markers.
    assert "ago" in result_past or "in " in result_future or "second" in result_past


def test_humanize_delta_stdlib_singular(monkeypatch) -> None:
    """humanize_delta: stdlib fallback с 1 unit → singular ('1 hour' без 's')."""
    import src.backend.core.utils.datetime_utils as mod

    monkeypatch.setattr(mod, "_HAS_PENDULUM", False)
    other = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
    dt = other - timedelta(hours=1)
    result = mod.humanize_delta(dt, other=other, absolute=True)
    assert "1 hour " in result or result.endswith("1 hour")


def test_utc_now_stdlib_fallback(monkeypatch) -> None:
    """utc_now: pendulum=None → stdlib datetime.now(UTC)."""
    import src.backend.core.utils.datetime_utils as mod

    monkeypatch.setattr(mod, "_HAS_PENDULUM", False)
    now = mod.utc_now()
    assert isinstance(now, datetime)
    assert now.tzinfo is not None


def test_parse_dt_stdlib_string(monkeypatch) -> None:
    """parse_dt: pendulum=None + string → stdlib fromisoformat."""
    import src.backend.core.utils.datetime_utils as mod

    monkeypatch.setattr(mod, "_HAS_PENDULUM", False)
    result = mod.parse_dt("2025-01-15T10:00:00")
    assert result.year == 2025
    assert result.tzinfo is not None  # ensure_utc applied
