"""Incident Analyst — read-only diagnostic hypothesis generator (Wave 3 #23).

Проблема:
    Анализ инцидента занимает много времени:
    - Нужно собрать trace + logs + recent deploys.
    - Сопоставить с известными failure patterns.
    - Сформулировать гипотезы с evidence.
    - Предложить safe actions (replay, rollback, scale).

Решение:
    ``IncidentAnalyst`` — pure-Python diagnostic helper:

    1. ``IncidentContext`` — error + trace_id + recent_deploys + route + tenant.
    2. ``Hypothesis`` — ranked diagnostic hypothesis с confidence + evidence.
    3. ``Recommendation`` — suggested action (replay/rollback/scale).
    4. ``IncidentAnalyst.analyze(ctx)`` → list of hypotheses + recommendations.
    5. Pattern matching на known error types (timeout, OOM, connection, schema).
    6. Read-only: NO write actions, only suggestions.

Использование::

    from src.backend.core.incident_analyst import (
        IncidentAnalyst, IncidentContext, get_incident_analyst,
    )

    analyst = get_incident_analyst()
    ctx = IncidentContext(
        error_type="TimeoutError",
        trace_id="trace-abc",
        route_id="order-create",
        tenant_id="t1",
        recent_deploys=["v1.2.3 at 2026-09-11 10:00"],
    )
    report = analyst.analyze(ctx)
    for hyp in report.hypotheses:
        print(f"{hyp.confidence:.0%}: {hyp.title}")
        print(f"  Evidence: {hyp.evidence}")
"""

from __future__ import annotations

from src.backend.core.incident_analyst.analyst import (
    Hypothesis,
    IncidentAnalyst,
    IncidentContext,
    IncidentReport,
    Recommendation,
    get_incident_analyst,
)

__all__ = (
    "Hypothesis",
    "IncidentAnalyst",
    "IncidentContext",
    "IncidentReport",
    "Recommendation",
    "get_incident_analyst",
)
