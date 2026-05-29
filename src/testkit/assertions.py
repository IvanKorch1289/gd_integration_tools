"""Assertion helpers for plugin tests (K5 S19 W3, S-L10-1).

Provides :func:`assert_audit_event` and :func:`assert_metric_recorded`
for verifying that code under test emits audit events and metrics
correctly.

Example usage::

    from src.testkit import (
        assert_audit_event,
        assert_metric_recorded,
    )
    from src.backend.infrastructure.observability.memory_metrics import MemoryMetricsBackend

    # Collect audit events via audit_callback fixture
    events: list[dict] = []
    assert_audit_event(
        events,
        event="user.login",
        actor="user-42",
        outcome="success",
    )

    # Collect metrics via MemoryMetricsBackend snapshot
    metrics = MemoryMetricsBackend()
    metrics.inc_counter("auth.login", labels={"tenant": "acme"})
    assert_metric_recorded(metrics, "auth.login", labels={"tenant": "acme"}, value=1.0)
"""

from __future__ import annotations

from src.backend.core.interfaces.audit import AuditRecord
from src.backend.infrastructure.observability.memory_metrics import MemoryMetricsBackend

__all__ = ("assert_audit_event", "assert_metric_recorded")


class _AssertionError(AssertionError):
    """Raised when an assertion helper fails."""

    ...


def assert_audit_event(
    events: list[AuditRecord],
    *,
    event: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    outcome: str | None = None,
    resource: str | None = None,
    correlation_id: str | None = None,
    exact: bool = False,
) -> AuditRecord:
    """Assert that ``events`` contains a matching audit record.

    At least one of ``event``, ``actor``, ``action``, ``outcome``,
    ``resource``, or ``correlation_id`` must be provided.

    Args:
        events: List of :class:`AuditRecord` objects to search.
        event: Match ``events[i]["event"] == event`` if provided.
        actor: Match ``events[i]["actor"] == actor`` if provided.
        action: Match ``events[i]["action"] == action`` if provided.
        outcome: Match ``events[i]["outcome"] == outcome`` if provided.
        resource: Match ``events[i]["resource"] == resource`` if provided.
        correlation_id: Match ``events[i]["correlation_id"] == correlation_id``
            if provided.
        exact: If ``True``, all provided fields must exactly match; if
            ``False`` (default), only the non-None criteria are checked.

    Returns:
        The matching :class:`AuditRecord`.

    Raises:
        AssertionError: If no matching event is found, or if ``exact=True``
            and an event matches criteria but has extra fields.

    Example::

        events: list[AuditRecord] = []
        # ... code that appends to events ...
        record = assert_audit_event(events, event="authorization.decision")
        assert record["outcome"] == "allow"
    """
    if not events:
        raise _AssertionError("assert_audit_event: events list is empty")

    criteria = {
        k: v
        for k, v in {
            "event": event,
            "actor": actor,
            "action": action,
            "outcome": outcome,
            "resource": resource,
            "correlation_id": correlation_id,
        }.items()
        if v is not None
    }

    if not criteria:
        raise _AssertionError(
            "assert_audit_event: at least one filter criterion must be provided"
        )

    for record in events:
        if not all(record.get(k) == v for k, v in criteria.items()):
            continue

        if exact:
            extra = set(record.keys()) - set(criteria.keys())
            if extra:
                continue  # skip records with extra fields

        return record

    criteria_str = ", ".join(f"{k}={v!r}" for k, v in criteria.items())
    raise _AssertionError(
        f"assert_audit_event: no event found matching {criteria_str}. "
        f"Available events: {events}"
    )


def assert_metric_recorded(
    backend: MemoryMetricsBackend,
    name: str,
    *,
    labels: dict[str, str] | None = None,
    value: float | None = None,
    at_least: float | None = None,
    operator: str = "==",
) -> float:
    """Assert that a metric was recorded in ``backend``.

    Exactly one of ``value`` or ``at_least`` must be provided.

    Args:
        backend: :class:`MemoryMetricsBackend` instance to query.
        name: Metric name to look up (e.g. ``"auth.login"``).
        labels: Optional label filter; only metrics with matching
            label key-value pairs are considered.
        value: Assert that the metric equals this value exactly.
        at_least: Assert that the metric is greater than or equal to this.
        operator: Comparison operator for ``value`` (default ``"=="``);
            supported: ``"=="``, ``">="``, ``"<="``, ``">"``, ``"<"``.

    Returns:
        The recorded metric value.

    Raises:
        AssertionError: If the metric is not found, or if the comparison
            fails.

    Example::

        backend = MemoryMetricsBackend()
        backend.inc_counter("auth.login", labels={"tenant": "acme"})
        backend.inc_counter("auth.login", labels={"tenant": "acme"})
        val = assert_metric_recorded(backend, "auth.login", labels={"tenant": "acme"}, at_least=2.0)
        assert val >= 2.0
    """
    snapshot = backend.snapshot()

    # Normalize labels to empty dict for consistent key lookup
    labels = labels or {}

    # Build the expected key format (same as MemoryMetricsBackend._key)
    def _key(n: str, lbls: dict[str, str] | None) -> str:
        if not lbls:
            return n
        parts = ",".join(f"{k}={lbls[k]}" for k in sorted(lbls))
        return f"{n}{{{parts}}}"

    expected_key = _key(name, labels)

    # Check counters first
    if expected_key in snapshot.get("counters", {}):
        recorded = snapshot["counters"][expected_key]
    elif expected_key in snapshot.get("gauges", {}):
        recorded = snapshot["gauges"][expected_key]
    else:
        raise _AssertionError(
            f"assert_metric_recorded: metric {name} with labels={labels!r} "
            f"not found in backend snapshot. Available keys: {list(snapshot.get('counters', {}).keys())}"
        )

    # Validate using the specified operator
    if value is not None:
        if operator == "==":
            if recorded != value:
                raise _AssertionError(
                    f"assert_metric_recorded: {name}{labels} == {recorded}, expected {value}"
                )
        elif operator == ">=":
            if recorded < value:
                raise _AssertionError(
                    f"assert_metric_recorded: {name}{labels} == {recorded}, expected >= {value}"
                )
        elif operator == "<=":
            if recorded > value:
                raise _AssertionError(
                    f"assert_metric_recorded: {name}{labels} == {recorded}, expected <= {value}"
                )
        elif operator == ">":
            if recorded <= value:
                raise _AssertionError(
                    f"assert_metric_recorded: {name}{labels} == {recorded}, expected > {value}"
                )
        elif operator == "<":
            if recorded >= value:
                raise _AssertionError(
                    f"assert_metric_recorded: {name}{labels} == {recorded}, expected < {value}"
                )
        else:
            raise ValueError(f"assert_metric_recorded: unknown operator {operator!r}")
    elif at_least is not None:
        if recorded < at_least:
            raise _AssertionError(
                f"assert_metric_recorded: {name}{labels} == {recorded}, expected >= {at_least}"
            )
    else:
        raise _AssertionError(
            "assert_metric_recorded: must provide either `value` or `at_least`"
        )

    return recorded
