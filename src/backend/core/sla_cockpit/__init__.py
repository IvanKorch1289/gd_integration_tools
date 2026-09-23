"""SLA/SLO Management Cockpit (Wave 4 #74).

Проблема:
    SLO определяется per-tenant/per-route (latency, availability, error rate),
    но:
    - Нет central registry для SLO definitions.
    - Нет единого reporting формата.
    - Нет alerting integration (alert при breach).
    - Нет trend analysis (improvement/regression detection).

Решение:
    ``SLA_Cockpit`` — централизованный cockpit для SLO/SLA management:

    1. ``SLO`` dataclass (latency_p99_ms, availability, error_rate).
    2. ``SLARegistry`` — register/get SLO per (tenant_id, route_id, scope).
    3. ``SLOMeasurement`` — recorded metric snapshot (actual vs SLO).
    4. ``SLOEvaluator`` — evaluate measurements, detect breaches.
    5. ``SLOReport`` — aggregate report для operator/SRE.

Использование::

    from src.backend.core.sla_cockpit import (  # noqa: F401 — re-export
        SLO, SLARegistry, SLOEvaluator, SLOStatus,
    )

    registry = get_sla_registry()
    registry.register(SLO(
        tenant_id="t1",
        route_id="order-create",
        latency_p99_ms=500,
        availability=0.999,
        error_rate=0.01,
    ))

    evaluator = SLOEvaluator(registry)
    status = evaluator.evaluate(
        tenant_id="t1",
        route_id="order-create",
        measurement=SLOMeasurement(
            timestamp=time.time(),
            latency_p99_ms=600,  # BREACH!
            availability=0.9999,
            error_rate=0.005,
        )
    )
    if status == SLOStatus.BREACH:
        # Alert SRE
        ...
"""

from __future__ import annotations

from src.backend.core.sla_cockpit.cockpit import (  # noqa: F401 — re-export
    SLOCockpit,
    SLOMeasurement,
    SLOReport,
    SLOStatus,
    get_sla_cockpit,
)
from src.backend.core.sla_cockpit.evaluator import (  # noqa: F401 — re-export
    SLOBreachDetail,
    SLOEvaluation,
    SLOEvaluator,
    SLOPeriodReport,
    aggregate_evaluations,
    evaluate_slo,
)
from src.backend.core.sla_cockpit.registry import SLO, SLARegistry, get_sla_registry

__all__ = (
    "SLO",
    "SLOBreachDetail",
    "SLOCockpit",
    "SLOEvaluator",
    "SLOEvaluation",
    "SLOMeasurement",
    "SLOPeriodReport",
    "SLOReport",
    "SLARegistry",
    "SLOStatus",
    "aggregate_evaluations",
    "evaluate_slo",
    "get_sla_cockpit",
    "get_sla_registry",
)
