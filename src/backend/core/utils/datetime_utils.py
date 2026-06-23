"""Datetime utilities + pendulum adoption shim (S57 W1).

Project context:
* ``datetime`` (stdlib) — 193 usages; remains backward-compat substrate.
* ``pendulum`` (3.2+, S57 W1 dep) — drop-in replacement с IANA tz,
  humanize (``dt.diff_for_humans()``), period arithmetic.

Strategy (S57+):
* **New code** (S57+ новые файлы) — prefer ``pendulum.now()`` / ``pendulum.parse()``.
* **Old code** — gradual migration; ``pendulum.DateTime`` IS ``datetime.datetime``
  (subclass), поэтому ``isinstance(dt, datetime.datetime)`` continues to work.
* **No-mass-refactor** — 193 импортов datetime мигрируем точечно (hot paths, audit,
  lineage, invoker). Без ROI-обоснования — НЕ ТРОГАЕМ.

This shim provides:
* :data:`utc_now` — timezone-aware UTC now (pendulum if available, stdlib fallback).
* :func:`parse_dt` — unified parser (ISO 8601, RFC 3339, unix timestamp, datetime).
* :func:`humanize_delta` — ``dt.diff_for_humans()`` wrapper.
* :func:`ensure_utc` — naive → UTC aware conversion.

Thread-safe: all functions pure (no shared state). Pendulum.DateTime is immutable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

try:
    import pendulum
    from pendulum import DateTime as _PendulumDateTime

    _HAS_PENDULUM = True
except ImportError:  # pragma: no cover — fallback на stdlib
    pendulum = None  # type: ignore[assignment]
    _PendulumDateTime = datetime  # type: ignore[assignment,misc]
    _HAS_PENDULUM = False

__all__ = (
    "ensure_utc",
    "humanize_delta",
    "is_pendulum_available",
    "parse_dt",
    "utc_now",
)


def is_pendulum_available() -> bool:
    """True если pendulum установлен и importable."""
    return _HAS_PENDULUM


def utc_now() -> datetime:
    """Timezone-aware UTC now (pendulum если available, иначе stdlib).

    Return type всегда ``datetime.datetime`` (pendulum.DateTime — subclass),
    поэтому existing code с ``isinstance(dt, datetime)`` работает unchanged.

    Example::

        now = utc_now()
        # both pendulum.DateTime и stdlib.datetime совместимы
    """
    if _HAS_PENDULUM:
        return pendulum.now(tz=timezone.utc)  # type: ignore[return-value]
    return datetime.now(tz=timezone.utc)


def parse_dt(value: Any) -> datetime:
    """Unified datetime parser.

    Args:
        value: input. Поддерживает:
            * ``datetime`` instance — passed through (ensure_utc applied).
            * ``int`` / ``float`` — unix timestamp (seconds, or ms если > 1e12).
            * ``str`` — ISO 8601 / RFC 3339 (через pendulum.parse).
            * ``None`` → :func:`utc_now`.

    Returns:
        ``datetime`` (tz-aware, UTC).

    Example::

        parse_dt("2025-01-15T10:00:00Z")
        parse_dt(1736935200)
        parse_dt(1736935200000)  # ms
        parse_dt(datetime(2025, 1, 15))  # naive → UTC applied
    """
    if value is None:
        return utc_now()
    if isinstance(value, datetime):
        return ensure_utc(value)
    if isinstance(value, (int, float)):
        # Heuristic: > 1e12 → milliseconds (post-2001 в ms); else seconds.
        if value > 1e12:
            return ensure_utc(datetime.fromtimestamp(value / 1000.0, tz=timezone.utc))
        return ensure_utc(datetime.fromtimestamp(value, tz=timezone.utc))
    if isinstance(value, str):
        if not _HAS_PENDULUM:
            # stdlib ISO 8601 parser (Python 3.11+)
            return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        return ensure_utc(pendulum.parse(value))  # type: ignore[union-attr]
    raise TypeError(f"parse_dt: unsupported type {type(value).__name__}")


def ensure_utc(dt: datetime) -> datetime:
    """Naive datetime → UTC aware. Aware datetime → converted to UTC.

    Args:
        dt: input datetime (naive или aware).

    Returns:
        ``datetime`` с ``tzinfo=timezone.utc``.

    Example::

        ensure_utc(datetime(2025, 1, 15, 10, 0))  # naive → UTC assumed
        ensure_utc(parse("2025-01-15T10:00:00+05:00"))  # +05:00 → UTC
    """
    if dt.tzinfo is None:
        # Naive datetime — assume UTC (no local-tz surprise).
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def humanize_delta(
    dt: datetime, other: datetime | None = None, absolute: bool = True
) -> str:
    """Human-readable diff между ``dt`` и ``other`` (default: now).

    Args:
        dt: target datetime.
        other: reference datetime (default ``utc_now()``).
        absolute: если True — без знака "in"/"ago" (для "last 3 hours" use cases).

    Returns:
        str ("3 hours ago", "in 2 days", "5 minutes"). Fallback на stdlib
        вычисление если pendulum недоступен.

    Example::

        past = utc_now().replace(hour=utc_now().hour - 3)
        humanize_delta(past)  # "3 hours ago"
    """
    if other is None:
        other = utc_now()
    if _HAS_PENDULUM:
        # pendulum.diff_for_humans поддерживает absolute=True.
        return _PendulumDateTime.diff_for_humans(  # type: ignore[union-attr]
            _PendulumDateTime.instance(dt),  # type: ignore[union-attr]
            _PendulumDateTime.instance(other),  # type: ignore[union-attr]
            absolute=absolute,
        )
    # stdlib fallback — простая "Xs ago" / "in Xs" formatting.
    delta = dt - other
    seconds = int(delta.total_seconds())
    if seconds == 0:
        return "now"
    if absolute:
        seconds = abs(seconds)
    sign = "" if absolute else ("in " if seconds > 0 else "")
    suffix = "" if absolute else (" ago" if seconds < 0 else "")
    secs = abs(seconds)
    if secs < 60:
        return f"{sign}{secs} second{'s' if secs != 1 else ''}{suffix}".strip()
    if secs < 3600:
        m = secs // 60
        return f"{sign}{m} minute{'s' if m != 1 else ''}{suffix}".strip()
    if secs < 86400:
        h = secs // 3600
        return f"{sign}{h} hour{'s' if h != 1 else ''}{suffix}".strip()
    d = secs // 86400
    return f"{sign}{d} day{'s' if d != 1 else ''}{suffix}".strip()
