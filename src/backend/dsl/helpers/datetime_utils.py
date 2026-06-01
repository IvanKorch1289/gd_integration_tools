"""Datetime helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

__all__ = ("now", "add_days", "to_iso8601")


def now(tz: str | None = None) -> datetime:
    if tz is None:
        return datetime.now(tz=timezone.utc)
    from zoneinfo import ZoneInfo

    return datetime.now(tz=ZoneInfo(tz))


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


def to_iso8601(dt: datetime) -> str:
    return dt.isoformat()
