"""Unit-тесты cron_validator — Sprint 12 K3 W2.

Сценарии:
    * valid 5-field cron;
    * valid 6-field (с секундами);
    * невалидное выражение → is_valid=False;
    * timezone-aware Next executions;
    * edge: Feb 29 (високосный год);
    * graceful когда croniter не установлен — is_valid=False с error.

Если croniter отсутствует в окружении — тесты positive cases пропускаются
через ``pytest.importorskip``.
"""

# ruff: noqa: S101

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.backend.infrastructure.scheduler.cron_validator import (
    CronValidationResult,
    validate_cron_expression,
)

croniter_mod = pytest.importorskip("croniter", reason="croniter не установлен в текущем окружении")


def test_valid_5field_weekday_business_hours() -> None:
    base = datetime(2026, 5, 18, 8, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    result = validate_cron_expression(
        "0 9 * * 1-5",
        timezone="Europe/Moscow",
        preview_count=5,
        base=base,
    )
    assert result.is_valid
    assert len(result.next_executions) == 5
    for dt in result.next_executions:
        assert dt.weekday() < 5
        assert dt.hour == 9
        assert dt.minute == 0


def test_valid_6field_with_seconds() -> None:
    base = datetime(2026, 5, 20, 12, 0, 0, tzinfo=ZoneInfo("UTC"))
    result = validate_cron_expression(
        "30 0 9 * * 1-5",
        timezone="UTC",
        preview_count=3,
        base=base,
    )
    assert result.is_valid
    for dt in result.next_executions:
        assert dt.second == 30


def test_invalid_expression() -> None:
    result = validate_cron_expression(
        "this is not cron",
        timezone="UTC",
        preview_count=5,
    )
    assert not result.is_valid
    assert result.error is not None
    assert result.next_executions == ()


def test_invalid_timezone() -> None:
    result = validate_cron_expression(
        "0 9 * * *",
        timezone="Mars/Olympus",
        preview_count=5,
    )
    assert not result.is_valid
    assert result.error is not None


def test_timezone_aware_next() -> None:
    base = datetime(2026, 5, 20, 8, 0, tzinfo=ZoneInfo("UTC"))
    result = validate_cron_expression(
        "0 12 * * *",
        timezone="Europe/Moscow",
        preview_count=1,
        base=base,
    )
    assert result.is_valid
    next_dt = result.next_executions[0]
    assert next_dt.tzinfo is not None
    assert next_dt.utcoffset().total_seconds() == 3 * 3600
    assert next_dt.hour == 12


def test_leap_year_feb_29() -> None:
    base = datetime(2028, 2, 27, 0, 0, tzinfo=ZoneInfo("UTC"))
    result = validate_cron_expression(
        "0 0 29 2 *",
        timezone="UTC",
        preview_count=2,
        base=base,
    )
    assert result.is_valid
    first = result.next_executions[0]
    assert first.month == 2
    assert first.day == 29


def test_preview_count_clamped() -> None:
    result = validate_cron_expression(
        "* * * * *",
        timezone="UTC",
        preview_count=999,
    )
    assert result.is_valid
    assert len(result.next_executions) == 50


def test_preview_count_min_clamped_to_one() -> None:
    result = validate_cron_expression(
        "* * * * *",
        timezone="UTC",
        preview_count=0,
    )
    assert result.is_valid
    assert len(result.next_executions) == 1


def test_result_is_frozen_dataclass() -> None:
    result = validate_cron_expression(
        "0 9 * * *",
        timezone="UTC",
        preview_count=1,
    )
    with pytest.raises(Exception):
        result.is_valid = False  # type: ignore[misc]


def test_dataclass_fields() -> None:
    result = validate_cron_expression(
        "0 9 * * *",
        timezone="UTC",
        preview_count=2,
    )
    assert isinstance(result, CronValidationResult)
    assert result.expression == "0 9 * * *"
    assert result.timezone == "UTC"
