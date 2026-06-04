"""Cron expression валидатор + preview — Sprint 12 K3 W2.

Public API:

* :func:`validate_cron_expression` — синтаксис + timezone проверка +
  preview Next N executions.
* :class:`CronValidationResult` — результат валидации с deterministic
  preview list.

Зависимости: ``croniter>=2.0.0`` (S0 carryover уже подтверждено), ``zoneinfo``
из stdlib (Python 3.9+). Без ``pendulum`` — стандартный ``zoneinfo``
покрывает DST-edge-cases для Europe/Moscow и других timezone.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__all__ = ("CronValidationError", "CronValidationResult", "validate_cron_expression")


class CronValidationError(ValueError):
    """Невалидное cron-выражение или timezone."""


@dataclass(frozen=True, slots=True)
class CronValidationResult:
    """Результат валидации cron + preview executions."""

    expression: str
    timezone: str
    is_valid: bool
    next_executions: tuple[datetime, ...]
    error: str | None = None


def validate_cron_expression(
    expression: str,
    *,
    timezone: str = "Europe/Moscow",
    preview_count: int = 5,
    base: datetime | None = None,
) -> CronValidationResult:
    """Валидирует cron-выражение и возвращает preview из ``preview_count`` next
    executions.

    Поддерживает 5-полевой (``min hour day month weekday``) и 6-полевой
    (``sec min hour day month weekday``) форматы croniter.

    Args:
        expression: cron-строка.
        timezone: IANA timezone name (``Europe/Moscow``, ``UTC``, etc).
        preview_count: число следующих выполнений (1..50, clamp).
        base: опц. base datetime — для deterministic тестов. По умолчанию
            ``datetime.now(tz=ZoneInfo(timezone))``.

    Returns:
        :class:`CronValidationResult` с ``is_valid`` + ``next_executions``.
    """
    preview_count = max(1, min(preview_count, 50))

    try:
        tz = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        return CronValidationResult(
            expression=expression,
            timezone=timezone,
            is_valid=False,
            next_executions=(),
            error=f"Невалидный timezone {timezone!r}: {exc}",
        )

    try:
        from croniter import croniter
    except ImportError:
        return CronValidationResult(
            expression=expression,
            timezone=timezone,
            is_valid=False,
            next_executions=(),
            error=(
                "Библиотека croniter не установлена. "
                "Добавьте в pyproject.toml: 'croniter>=2.0.0'."
            ),
        )

    base_dt = base or datetime.now(tz=tz)
    if base_dt.tzinfo is None:
        base_dt = base_dt.replace(tzinfo=tz)
    else:
        base_dt = base_dt.astimezone(tz)

    try:
        fields = expression.split()
        second_at_beginning = len(fields) == 6
        itr = croniter(expression, base_dt, second_at_beginning=second_at_beginning)
    except (ValueError, KeyError) as exc:
        return CronValidationResult(
            expression=expression,
            timezone=timezone,
            is_valid=False,
            next_executions=(),
            error=f"Невалидное cron-выражение: {exc}",
        )

    next_runs: list[datetime] = []
    for _ in range(preview_count):
        next_dt: datetime = itr.get_next(datetime)
        if next_dt.tzinfo is None:
            next_dt = next_dt.replace(tzinfo=tz)
        next_runs.append(next_dt)

    return CronValidationResult(
        expression=expression,
        timezone=timezone,
        is_valid=True,
        next_executions=tuple(next_runs),
    )


def list_supported_timezones() -> Sequence[str]:
    """Список IANA timezone (для Streamlit selectbox)."""
    try:
        from zoneinfo import available_timezones

        return sorted(available_timezones())
    except Exception as _:
        return (
            "UTC",
            "Europe/Moscow",
            "Europe/London",
            "America/New_York",
            "Asia/Tokyo",
        )
