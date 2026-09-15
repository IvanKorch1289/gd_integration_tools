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


@dataclass(slots=True)
class SLOPeriodReport:
    """Aggregated SLO report over a period (Wave 175+ P1.3).

    Attributes:
        slo_id: SLO identifier.
        slo_version: SLO version.
        start_time: Period start (Unix timestamp).
        end_time: Period end.
        evaluation_count: Number of evaluations in period.
        healthy_count: Count of HEALTHY evaluations.
        at_risk_count: Count of AT_RISK evaluations.
        breach_count: Count of BREACH evaluations.
        worst_latency_p99_ms: Highest observed p99 latency.
        worst_error_rate: Highest observed error rate.
    """

    slo_id: str
    slo_version: str
    start_time: float
    end_time: float
    evaluation_count: int = 0
    healthy_count: int = 0
    at_risk_count: int = 0
    breach_count: int = 0
    worst_latency_p99_ms: float = 0.0
    worst_error_rate: float = 0.0

    @property
    def availability(self) -> float:
        """Computed availability ratio (healthy / total)."""
        if self.evaluation_count == 0:
            return 1.0
        return self.healthy_count / self.evaluation_count

    @property
    def period_seconds(self) -> float:
        return max(0.0, self.end_time - self.start_time)

    def to_dict(self) -> dict:
        return {
            "slo_id": self.slo_id,
            "slo_version": self.slo_version,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "period_seconds": self.period_seconds,
            "evaluation_count": self.evaluation_count,
            "healthy_count": self.healthy_count,
            "at_risk_count": self.at_risk_count,
            "breach_count": self.breach_count,
            "availability": self.availability,
            "worst_latency_p99_ms": self.worst_latency_p99_ms,
            "worst_error_rate": self.worst_error_rate,
        }


def aggregate_evaluations(
    evaluations: list[SLOEvaluation],
    slo: "SLO",
    start_time: float,
    end_time: float,
) -> SLOPeriodReport:
    """Aggregate multiple SLOEvaluation в period report.

    Args:
        evaluations: List of SLOEvaluation (all for same SLO).
        slo: The SLO definition.
        start_time: Period start.
        end_time: Period end.

    Returns:
        SLOPeriodReport with aggregated counts.
    """

    report = SLOPeriodReport(
        slo_id=slo.tenant_id + ":" + (
            next(
                (e.route_id for e in evaluations if e.route_id),
                slo.tenant_id,
            )
        ),
        slo_version=slo.tenant_id,
        start_time=start_time,
        end_time=end_time,
    )
    for e in evaluations:
        if e.slo is not slo:
            continue
        report.evaluation_count += 1
        if e.status == SLOStatus.HEALTHY:
            report.healthy_count += 1
        elif e.status == SLOStatus.AT_RISK:
            report.at_risk_count += 1
        elif e.status == SLOStatus.BREACH:
            report.breach_count += 1
        if e.actual_latency_p99_ms is not None and (
            report.worst_latency_p99_ms is None
            or e.actual_latency_p99_ms > report.worst_latency_p99_ms
        ):
            report.worst_latency_p99_ms = e.actual_latency_p99_ms
        if e.actual_error_rate is not None and (
            report.worst_error_rate is None
            or e.actual_error_rate > report.worst_error_rate
        ):
            report.worst_error_rate = e.actual_error_rate
    return report
