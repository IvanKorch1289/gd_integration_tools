"""SLO evaluator — measures actual vs SLO (Wave 4 #74)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.backend.core.sla_cockpit.registry import SLO, SLOStatus

logger = logging.getLogger(__name__)

__all__ = ("SLOEvaluator", "evaluate_slo")


@dataclass(slots=True)
class SLOBreachDetail:
    """Detail of one breach (which dimension exceeded budget)."""

    dimension: str  # "latency" | "availability" | "error_rate"
    actual: float
    budget: float
    severity: str  # "breach" | "at_risk"

    @property
    def is_breach(self) -> bool:
        return self.severity == "breach"


@dataclass(slots=True)
class SLOEvaluation:
    """Evaluation result для one (tenant_id, route_id, measurement)."""

    tenant_id: str
    route_id: str
    status: SLOStatus
    breaches: list[SLOBreachDetail] = field(default_factory=list)
    slo: SLO | None = None
    actual_latency_p99_ms: float | None = None
    actual_availability: float | None = None
    actual_error_rate: float | None = None

    @property
    def has_breach(self) -> bool:
        return self.status == SLOStatus.BREACH


def evaluate_slo(
    slo: SLO,
    latency_p99_ms: float | None = None,
    availability: float | None = None,
    error_rate: float | None = None,
    *,
    at_risk_threshold: float = 0.9,
) -> SLOEvaluation:
    """Evaluate single SLO against actual metrics.

    Args:
        slo: SLO definition.
        latency_p99_ms: Actual P99 latency (None → unknown).
        availability: Actual availability (None → unknown).
        error_rate: Actual error rate (None → unknown).
        at_risk_threshold: % of budget below which = at_risk (default 0.9).

    Returns:
        :class:`SLOEvaluation` с status + breach details.
    """
    breaches: list[SLOBreachDetail] = []

    # Check latency.
    if latency_p99_ms is not None:
        ratio = latency_p99_ms / slo.latency_p99_ms
        if ratio > 1.0:
            breaches.append(
                SLOBreachDetail(
                    dimension="latency",
                    actual=latency_p99_ms,
                    budget=slo.latency_p99_ms,
                    severity="breach",
                )
            )
        elif at_risk_threshold <= ratio < 1.0:
            breaches.append(
                SLOBreachDetail(
                    dimension="latency",
                    actual=latency_p99_ms,
                    budget=slo.latency_p99_ms,
                    severity="at_risk",
                )
            )

    # Check availability (lower is worse).
    if availability is not None:
        # availability budget margin (above target) → at_risk.
        margin = 1.0 - slo.availability
        # Buffer: how much above budget before at_risk.
        buffer = margin * (1 - at_risk_threshold)
        if availability < slo.availability:
            breaches.append(
                SLOBreachDetail(
                    dimension="availability",
                    actual=availability,
                    budget=slo.availability,
                    severity="breach",
                )
            )
        elif availability < slo.availability + buffer:
            breaches.append(
                SLOBreachDetail(
                    dimension="availability",
                    actual=availability,
                    budget=slo.availability,
                    severity="at_risk",
                )
            )

    # Check error rate (higher is worse).
    if error_rate is not None and slo.error_rate > 0:
        ratio = error_rate / slo.error_rate
        if ratio > 1.0:
            breaches.append(
                SLOBreachDetail(
                    dimension="error_rate",
                    actual=error_rate,
                    budget=slo.error_rate,
                    severity="breach",
                )
            )
        elif at_risk_threshold <= ratio < 1.0:
            breaches.append(
                SLOBreachDetail(
                    dimension="error_rate",
                    actual=error_rate,
                    budget=slo.error_rate,
                    severity="at_risk",
                )
            )

    # Determine status.
    if any(b.severity == "breach" for b in breaches):
        status = SLOStatus.BREACH
    elif any(b.severity == "at_risk" for b in breaches):
        status = SLOStatus.AT_RISK
    elif all(v is None for v in [latency_p99_ms, availability, error_rate]):
        status = SLOStatus.UNKNOWN
    else:
        status = SLOStatus.HEALTHY

    return SLOEvaluation(
        tenant_id=slo.tenant_id,
        route_id=slo.route_id,
        status=status,
        breaches=breaches,
        slo=slo,
        actual_latency_p99_ms=latency_p99_ms,
        actual_availability=availability,
        actual_error_rate=error_rate,
    )


class SLOEvaluator:
    """Stateful evaluator с measurement history."""

    def __init__(self, registry: Any = None) -> None:
        from src.backend.core.sla_cockpit.registry import get_sla_registry

        self._registry = registry or get_sla_registry()
        self._history: list[SLOEvaluation] = []

    def evaluate(
        self,
        *,
        tenant_id: str,
        route_id: str,
        latency_p99_ms: float | None = None,
        availability: float | None = None,
        error_rate: float | None = None,
        **kwargs: Any,
    ) -> SLOEvaluation:
        """Evaluate SLO для (tenant_id, route_id)."""
        slo = self._registry.get(tenant_id, route_id)
        if slo is None:
            return SLOEvaluation(
                tenant_id=tenant_id,
                route_id=route_id,
                status=SLOStatus.UNKNOWN,
                slo=None,
            )

        evaluation = evaluate_slo(
            slo,
            latency_p99_ms=latency_p99_ms,
            availability=availability,
            error_rate=error_rate,
            **kwargs,
        )
        self._history.append(evaluation)
        return evaluation

    def history(self, *, limit: int | None = None) -> list[SLOEvaluation]:
        """Get evaluation history (most recent first)."""
        history = list(reversed(self._history))
        return history[:limit] if limit else history

    def clear_history(self) -> None:
        self._history.clear()
