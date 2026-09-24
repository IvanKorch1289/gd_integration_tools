"""Cost Attribution — per-route/tenant/agent cost tracking (Wave 4 #75).

Pure-Python implementation:
- @track_cost decorator для auto-tracking costs.
- CostRegistry — in-memory records.
- CostReport — aggregation by tenant/route/resource.
"""

from __future__ import annotations

import enum
import functools
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = (
    "CostAttribution",
    "CostRecord",
    "CostReport",
    "ResourceType",
    "get_cost_attribution",
    "get_cost_registry",
    "track_cost",
)


class ResourceType(str, enum.Enum):
    """Тип ресурса для cost attribution."""

    LLM_TOKENS = "llm_tokens"
    LLM_REQUESTS = "llm_requests"
    HTTP_REQUESTS = "http_requests"
    DB_QUERIES = "db_queries"
    MQ_MESSAGES = "mq_messages"
    STORAGE_OPS = "storage_ops"
    EXTERNAL_API = "external_api"
    COMPUTE_SECONDS = "compute_seconds"


@dataclass(slots=True)
class CostRecord:
    """Single cost event."""

    timestamp: float
    tenant_id: str
    route_id: str
    resource_type: ResourceType
    units: float
    cost_usd: float
    agent: str | None = None
    connector: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Сериализация записи затрат (для экспорта/дашборда)."""
        return {
            "timestamp": self.timestamp,
            "tenant_id": self.tenant_id,
            "route_id": self.route_id,
            "resource_type": self.resource_type.value,
            "units": self.units,
            "cost_usd": self.cost_usd,
            "agent": self.agent,
            "connector": self.connector,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class CostReport:
    """Aggregated cost report."""

    timestamp: float
    records: list[CostRecord] = field(default_factory=list)

    @property
    def total_cost_usd(self) -> float:
        """Суммарная стоимость в USD по всем записям."""
        return sum(r.cost_usd for r in self.records)

    @property
    def total_units(self) -> float:
        """Суммарное количество единиц (tokens/requests) по записям."""
        return sum(r.units for r in self.records)

    def by_tenant(self) -> dict[str, float]:
        """Стоимость, сгруппированная по tenant_id."""
        result: dict[str, float] = {}
        for r in self.records:
            result[r.tenant_id] = result.get(r.tenant_id, 0.0) + r.cost_usd
        return result

    def by_route(self) -> dict[str, float]:
        """Стоимость, сгруппированная по route_id."""
        result: dict[str, float] = {}
        for r in self.records:
            result[r.route_id] = result.get(r.route_id, 0.0) + r.cost_usd
        return result

    def by_resource(self) -> dict[str, float]:
        """Стоимость, сгруппированная по ресурсу (model/provider)."""
        result: dict[str, float] = {}
        for r in self.records:
            key = r.resource_type.value
            result[key] = result.get(key, 0.0) + r.cost_usd
        return result

    def by_agent(self) -> dict[str, float]:
        """Стоимость, сгруппированная по агенту."""
        result: dict[str, float] = {}
        for r in self.records:
            agent = r.agent or "(no-agent)"
            result[agent] = result.get(agent, 0.0) + r.cost_usd
        return result

    def top_consumers(self, limit: int = 5) -> list[tuple[tuple[str, str, str], float]]:
        """Top N (tenant_id, route_id, agent) by cost."""
        pairs: dict[tuple[str, str, str], float] = {}
        for r in self.records:
            key = (r.tenant_id, r.route_id, r.agent or "(no-agent)")
            pairs[key] = pairs.get(key, 0.0) + r.cost_usd
        return sorted(pairs.items(), key=lambda x: x[1], reverse=True)[:limit]

    def to_dict(self) -> dict[str, Any]:
        """Сериализация агрегата (срезы by_* + итоги)."""
        return {
            "timestamp": self.timestamp,
            "total_cost_usd": self.total_cost_usd,
            "total_units": self.total_units,
            "records_count": len(self.records),
            "by_tenant": self.by_tenant(),
            "by_route": self.by_route(),
            "by_resource": self.by_resource(),
            "by_agent": self.by_agent(),
        }


class CostAttribution:
    """In-memory cost registry + tracking."""

    def __init__(self) -> None:
        self._records: list[CostRecord] = []

    def record(
        self,
        *,
        tenant_id: str = "*",
        route_id: str = "*",
        resource_type: ResourceType,
        units: float,
        cost_usd: float,
        agent: str | None = None,
        connector: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CostRecord:
        """Add cost record."""
        rec = CostRecord(
            timestamp=time.time(),
            tenant_id=tenant_id,
            route_id=route_id,
            resource_type=resource_type,
            units=units,
            cost_usd=cost_usd,
            agent=agent,
            connector=connector,
            metadata=metadata or {},
        )
        self._records.append(rec)
        return rec

    def list_records(self) -> list[CostRecord]:
        """Все записи затрат (порядок вставки)."""
        return list(self._records)

    def list_for_tenant(self, tenant_id: str) -> list[CostRecord]:
        """Записи затрат конкретного тенанта."""
        return [r for r in self._records if r.tenant_id == tenant_id]

    def list_for_route(self, route_id: str) -> list[CostRecord]:
        """Записи затрат конкретного маршрута."""
        return [r for r in self._records if r.route_id == route_id]

    def size(self) -> int:
        """Количество записей в хранилище."""
        return len(self._records)

    def clear(self) -> None:
        """Полный сброс хранилища (для тестов/reload)."""
        self._records.clear()

    def purge_older_than(self, seconds: float, now: float | None = None) -> int:
        """Remove records older than ``seconds`` (Sprint 175+ P1.2).

        Args:
            seconds: Age threshold (records with timestamp < now - seconds
                are removed).
            now: Reference time (default: time.time()).

        Returns:
            Number of records removed.
        """
        if now is None:
            now = time.time()
        before = len(self._records)
        keep_from = 0
        for i, r in enumerate(self._records):
            if r.timestamp >= now - seconds:
                keep_from = i
                break
            keep_from = i + 1
        else:
            self._records.clear()
            return before
        if keep_from > 0:
            del self._records[:keep_from]
        return before - len(self._records)

    def generate_report(self) -> CostReport:
        """Generate aggregated CostReport from current records."""
        return CostReport(timestamp=time.time(), records=list(self._records))


_registry: CostAttribution | None = None


def get_cost_registry() -> CostAttribution:
    """Module-level singleton (legacy name)."""
    global _registry
    if _registry is None:
        _registry = CostAttribution()
    return _registry


def get_cost_attribution() -> CostAttribution:
    """Module-level singleton."""
    return get_cost_registry()


def reset_cost_attribution() -> None:
    """Reset singleton (test-only)."""
    global _registry
    _registry = None


def track_cost(
    resource_type: ResourceType,
    *,
    cost_per_unit: float,
    tenant_id_arg: str | None = None,
    route_id_arg: str | None = None,
    units_arg: str | None = None,
    units_default: float = 1.0,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: auto-track cost при вызове function.

    Args:
        resource_type: Type of resource (LLM_TOKENS, HTTP_REQUESTS, ...).
        cost_per_unit: Cost per unit (USD).
        tenant_id_arg: Argument name для tenant_id (например, "tenant_id").
        route_id_arg: Argument name для route_id.
        units_arg: Argument name для units (если None → units_default).
        units_default: Default units (если не указаны).

    Usage::

        @track_cost(ResourceType.LLM_TOKENS, cost_per_unit=0.0001,
                     tenant_id_arg="tenant_id", units_arg="tokens")
        async def call_llm(tenant_id: str, tokens: int):
            return await _openai(...)
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        # Capture defaults for closure.
        rt = resource_type
        cpu = cost_per_unit
        tenant_arg = tenant_id_arg
        route_arg = route_id_arg
        units_arg_name = units_arg

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                # Extract tenant_id / route_id / units from kwargs (or args).
                bound = inspect.signature(fn).bind_partial(*args, **kwargs)
                bound.apply_defaults()
                tenant = bound.arguments.get(tenant_arg, "*") if tenant_arg else "*"
                route = bound.arguments.get(route_arg, "*") if route_arg else "*"
                units = (
                    bound.arguments.get(units_arg_name, units_default)
                    if units_arg_name
                    else units_default
                )

                result = await fn(*args, **kwargs)
                # Record cost.
                cost = units * cpu
                get_cost_registry().record(
                    tenant_id=tenant,
                    route_id=route,
                    resource_type=rt,
                    units=units,
                    cost_usd=cost,
                )
                return result

            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = inspect.signature(fn).bind_partial(*args, **kwargs)
            bound.apply_defaults()
            tenant = bound.arguments.get(tenant_arg, "*") if tenant_arg else "*"
            route = bound.arguments.get(route_arg, "*") if route_arg else "*"
            units = (
                bound.arguments.get(units_arg_name, units_default)
                if units_arg_name
                else units_default
            )

            result = fn(*args, **kwargs)
            cost = units * cpu
            get_cost_registry().record(
                tenant_id=tenant,
                route_id=route,
                resource_type=rt,
                units=units,
                cost_usd=cost,
            )
            return result

        return sync_wrapper

    return decorator
