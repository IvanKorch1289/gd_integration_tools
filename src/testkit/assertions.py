"""Assertion helpers для audit events и metrics.

:func:`assert_audit_event` и :func:`assert_metric_recorded` — shortcut
assertions для написания читаемых test assertions.

Этот модуль — часть ``src/testkit/`` public API (K5 S19 W3).
"""

from __future__ import annotations

from typing import Any

__all__ = ("assert_audit_event", "assert_metric_recorded")


def assert_audit_event(
    events: list[dict[str, Any]],
    *,
    event_type: str,
    plugin: str | None = None,
    capability: str | None = None,
    outcome: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Find and return matching audit event from list.

    Args:
        events: список audit event dicts (например, из MockCapabilityGateway.checks).
        event_type: искомый тип события (например, ``"capability.check"``).
        plugin: опционально фильтровать по plugin.
        capability: опционально фильтровать по capability.
        outcome: опционально фильтровать по outcome (``"granted"`` / ``"denied"``).
        **extra: дополнительные key-value для точного совпадения.

    Returns:
        Найденный event dict.

    Raises:
        AssertionError: если событие не найдено или найдено больше одного.

    Example:
        >>> events = [{"event": "capability.check", "plugin": "my-plugin",
        ...            "capability": "db.read", "outcome": "granted"}]
        >>> assert_audit_event(events, event_type="capability.check",
        ...                    plugin="my-plugin", outcome="granted")
    """
    matching = [
        e for e in events
        if e.get("event") == event_type
    ]

    if plugin is not None:
        matching = [e for e in matching if e.get("plugin") == plugin]
    if capability is not None:
        matching = [e for e in matching if e.get("capability") == capability]
    if outcome is not None:
        matching = [e for e in matching if e.get("outcome") == outcome]

    for key, value in extra.items():
        matching = [e for e in matching if e.get(key) == value]

    if not matching:
        raise AssertionError(
            f"No audit event found matching: "
            f"event_type={event_type!r}, plugin={plugin!r}, "
            f"capability={capability!r}, outcome={outcome!r}, extra={extra}"
        )
    if len(matching) > 1:
        raise AssertionError(
            f"Multiple audit events found matching criteria ({len(matching)}): "
            f"first match: {matching[0]!r}"
        )

    return matching[0]


def assert_metric_recorded(
    metrics: list[dict[str, Any]],
    *,
    metric_name: str,
    labels: dict[str, str] | None = None,
    value: Any | None = None,
) -> dict[str, Any]:
    """Find and return matching metric from list.

    Args:
        metrics: список metric dicts (например, из mock metrics collector).
        metric_name: имя метрики (например, ``"workflow.start"``).
        labels: опционально фильтровать по labels dict.
        value: опционально проверять значение метрики.

    Returns:
        Найденный metric dict.

    Raises:
        AssertionError: если метрика не найдена или найдено больше одной.

    Example:
        >>> metrics = [{"name": "workflow.start", "labels": {"tenant": "t1"},
        ...            "value": 1}]
        >>> assert_metric_recorded(metrics, metric_name="workflow.start",
        ...                         labels={"tenant": "t1"})
    """
    matching = [m for m in metrics if m.get("name") == metric_name]

    if labels is not None:
        matching = [
            m for m in matching
            if all(m.get("labels", {}).get(k) == v for k, v in labels.items())
        ]

    if value is not None:
        matching = [m for m in matching if m.get("value") == value]

    if not matching:
        raise AssertionError(
            f"No metric found: name={metric_name!r}, "
            f"labels={labels!r}, value={value!r}"
        )
    if len(matching) > 1:
        raise AssertionError(
            f"Multiple metrics found ({len(matching)}): first: {matching[0]!r}"
        )

    return matching[0]
