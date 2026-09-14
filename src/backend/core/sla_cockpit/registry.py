"""SLO registry + SLO dataclass (Wave 4 #74)."""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ("SLO", "SLARegistry", "get_sla_registry")


class SLOStatus(str, enum.Enum):
    """SLO evaluation status."""

    HEALTHY = "healthy"  # все метрики в норме
    AT_RISK = "at_risk"  # approaching breach (90-99% of budget)
    BREACH = "breach"  # нарушение SLO
    UNKNOWN = "unknown"  # нет measurement


@dataclass(slots=True)
class SLO:
    """Service Level Objective definition.

    Attributes:
        tenant_id: Tenant scope (или "*" для global).
        route_id: Route scope (или "*" для всех routes tenant).
        latency_p99_ms: P99 latency budget (ms).
        availability: Availability target (0.0-1.0).
        error_rate: Max error rate (0.0-1.0).
        window_minutes: SLO evaluation window.
        owner: Team/person responsible.
        description: Human-readable description.
    """

    tenant_id: str = "*"
    route_id: str = "*"
    latency_p99_ms: float = 500.0
    availability: float = 0.999
    error_rate: float = 0.01
    window_minutes: int = 60
    owner: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "route_id": self.route_id,
            "latency_p99_ms": self.latency_p99_ms,
            "availability": self.availability,
            "error_rate": self.error_rate,
            "window_minutes": self.window_minutes,
            "owner": self.owner,
            "description": self.description,
        }


class SLARegistry:
    """In-memory registry SLO definitions."""

    def __init__(self) -> None:
        self._slo: dict[tuple[str, str], SLO] = {}

    def register(self, slo: SLO) -> None:
        """Register or overwrite SLO для (tenant_id, route_id)."""
        key = (slo.tenant_id, slo.route_id)
        self._slo[key] = slo

    def get(self, tenant_id: str, route_id: str) -> SLO | None:
        """Lookup SLO. Specific → wildcard fallback."""
        # Try specific match first.
        key = (tenant_id, route_id)
        if key in self._slo:
            return self._slo[key]
        # Try tenant-specific wildcard.
        tenant_key = (tenant_id, "*")
        if tenant_key in self._slo:
            return self._slo[tenant_key]
        # Try route-specific wildcard.
        route_key = ("*", route_id)
        if route_key in self._slo:
            return self._slo[route_key]
        # Try global wildcard.
        global_key = ("*", "*")
        if global_key in self._slo:
            return self._slo[global_key]
        return None

    def list_all(self) -> list[SLO]:
        return list(self._slo.values())

    def list_by_tenant(self, tenant_id: str) -> list[SLO]:
        return [
            slo for (tid, _), slo in self._slo.items() if tid == tenant_id or tid == "*"
        ]

    def size(self) -> int:
        return len(self._slo)

    def clear(self) -> None:
        self._slo.clear()


_registry: SLARegistry | None = None


def get_sla_registry() -> SLARegistry:
    global _registry
    if _registry is None:
        _registry = SLARegistry()
    return _registry


def reset_sla_registry() -> None:
    global _registry
    _registry = None
