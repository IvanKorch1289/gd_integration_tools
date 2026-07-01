"""Datetime helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

__all__ = ("add_days", "now", "to_iso8601")


def now(tz: str | None = None) -> datetime:
    """Текущее время в UTC (по умолчанию) или указанной IANA-зоне."""
    if tz is None:
        return datetime.now(tz=UTC)
    from zoneinfo import ZoneInfo

    return datetime.now(tz=ZoneInfo(tz))


def add_days(dt: datetime, days: int) -> datetime:
    """Прибавляет ``days`` дней к datetime (отрицательные значения допустимы)."""
    return dt + timedelta(days=days)


def to_iso8601(dt: datetime) -> str:
    """Преобразует datetime в ISO-8601 строку."""
    return dt.isoformat()
