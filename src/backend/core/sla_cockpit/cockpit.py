"""SLA Cockpit — high-level coordinator + measurement + report (Wave 4 #74)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from src.backend.core.sla_cockpit.evaluator import SLOEvaluation, SLOEvaluator
from src.backend.core.sla_cockpit.registry import SLOStatus

logger = __import__("logging").getLogger(__name__)

__all__ = ("SLOCockpit", "SLOMeasurement", "SLOReport", "get_sla_cockpit")


@dataclass(slots=True)
class SLOMeasurement:
    """Recorded SLO measurement snapshot."""

    timestamp: float
    tenant_id: str
    route_id: str
    latency_p99_ms: float | None = None
    availability: float | None = None
    error_rate: float | None = None


@dataclass(slots=True)
class SLOReport:
    """Aggregated SLO report для operator/SRE dashboard."""

    timestamp: float
    evaluations: list[SLOEvaluation] = field(default_factory=list)

    @property
    def total_slos(self) -> int:
        return len(self.evaluations)

    @property
    def breach_count(self) -> int:
        return sum(1 for e in self.evaluations if e.status == SLOStatus.BREACH)

    @property
    def at_risk_count(self) -> int:
        return sum(1 for e in self.evaluations if e.status == SLOStatus.AT_RISK)

    @property
    def healthy_count(self) -> int:
        return sum(1 for e in self.evaluations if e.status == SLOStatus.HEALTHY)

    @property
    def unknown_count(self) -> int:
        return sum(1 for e in self.evaluations if e.status == SLOStatus.UNKNOWN)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_slos": self.total_slos,
            "breach_count": self.breach_count,
            "at_risk_count": self.at_risk_count,
            "healthy_count": self.healthy_count,
            "unknown_count": self.unknown_count,
            "evaluations": [
                {
                    "tenant_id": e.tenant_id,
                    "route_id": e.route_id,
                    "status": e.status.value,
                    "breaches": [
                        {
                            "dimension": b.dimension,
                            "actual": b.actual,
                            "budget": b.budget,
                            "severity": b.severity,
                        }
                        for b in e.breaches
                    ],
                }
                for e in self.evaluations
            ],
        }


class SLOCockpit:
    """Coordinator: registry + evaluator + report generation."""

    def __init__(self) -> None:
        from src.backend.core.sla_cockpit.registry import get_sla_registry

        self._registry = get_sla_registry()
        self._evaluator = SLOEvaluator(registry=self._registry)

    def record(
        self,
        *,
        tenant_id: str,
        route_id: str,
        latency_p99_ms: float | None = None,
        availability: float | None = None,
        error_rate: float | None = None,
    ) -> SLOEvaluation:
        """Record measurement + evaluate."""
        return self._evaluator.evaluate(
            tenant_id=tenant_id,
            route_id=route_id,
            latency_p99_ms=latency_p99_ms,
            availability=availability,
            error_rate=error_rate,
        )

    def generate_report(self) -> SLOReport:
        """Generate aggregated report from current state."""
        evaluations = self._evaluator.history()
        return SLOReport(timestamp=time.time(), evaluations=evaluations)

    def clear_history(self) -> None:
        self._evaluator.clear_history()

    @property
    def registry(self) -> Any:
        return self._registry


_cockpit: SLOCockpit | None = None


def get_sla_cockpit() -> SLOCockpit:
    global _cockpit
    if _cockpit is None:
        _cockpit = SLOCockpit()
    return _cockpit


def reset_sla_cockpit() -> None:
    global _cockpit
    _cockpit = None
