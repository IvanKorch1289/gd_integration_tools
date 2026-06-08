"""WorkflowCostEstimator — Sprint 12 K3 W3 + K4 W2.

Pre-run estimation для workflow:

* Historical p50/p95 duration_ms из workflow_audit ClickHouse table;
* LLM tokens × model price (K4 W2 — _estimate_llm_cost);
* Compute seconds (= p95 duration / 1000);
* Storage bytes (приближение через avg payload size).

Точность ±20% относительно фактического run после ≥10 historical
executions (см. DoD K3 W3).

API:
    * :class:`CostEstimate` — frozen pydantic дataclass.
    * :class:`LLMCostBreakdown` — детализация по моделям (K4 W2).
    * :class:`WorkflowCostEstimator.estimate(workflow_id, version, input_size_bytes)`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("CostEstimate", "LLMCostBreakdown", "WorkflowCostEstimator")

_logger = get_logger("services.workflows.cost_estimator")


if TYPE_CHECKING:  # pragma: no cover
    pass


@dataclass(frozen=True, slots=True)
class LLMCostBreakdown:
    """Детализация LLM-стоимости по моделям (S12 K4 W2)."""

    per_model: dict[str, Decimal] = field(default_factory=dict)
    total_usd: Decimal = Decimal("0")
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """Pre-run estimation для workflow."""

    workflow_id: str
    version: str | None
    sample_size: int
    p50_duration_ms: float
    p95_duration_ms: float
    estimated_llm_tokens: int = 0
    estimated_cost_usd: Decimal = Decimal("0")
    estimated_compute_seconds: float = 0.0
    estimated_storage_bytes: int = 0
    llm_breakdown: LLMCostBreakdown | None = None


class WorkflowCostEstimator:
    """Pre-run cost estimator поверх historical ClickHouse данных.

    Args:
        clickhouse_client_factory: async-фабрика ClickHouse-клиента.
            При ``None`` используется ``clickhouse_connect.get_async_client``.
    """

    def __init__(self, clickhouse_client_factory: Any | None = None) -> None:
        self._client_factory = clickhouse_client_factory

    async def _get_client(self) -> Any:
        if self._client_factory is not None:
            return await self._client_factory()
        from clickhouse_connect import get_async_client

        from src.backend.core.config import settings

        host = (
            getattr(settings.clickhouse, "host", "localhost")
            if hasattr(settings, "clickhouse")
            else "localhost"
        )
        port = (
            getattr(settings.clickhouse, "port", 8123)
            if hasattr(settings, "clickhouse")
            else 8123
        )
        database = (
            getattr(settings.clickhouse, "database", "default")
            if hasattr(settings, "clickhouse")
            else "default"
        )
        return await get_async_client(host=host, port=port, database=database)

    async def estimate(
        self,
        *,
        workflow_id: str,
        version: str | None = None,
        input_size_bytes: int = 0,
        sample_period_days: int = 30,
    ) -> CostEstimate:
        """Возвращает :class:`CostEstimate` на основе historical ClickHouse
        данных за последние ``sample_period_days``.
        """
        from datetime import datetime, timedelta

        cutoff = datetime.now(UTC) - timedelta(days=sample_period_days)

        try:
            client = await self._get_client()
        except Exception as exc:
            _logger.warning(
                "WorkflowCostEstimator: CH unavailable (%s), returning defaults", exc
            )
            return CostEstimate(
                workflow_id=workflow_id,
                version=version,
                sample_size=0,
                p50_duration_ms=0.0,
                p95_duration_ms=0.0,
            )

        sql = (
            "SELECT "
            "  count() AS sample, "
            "  quantile(0.5)(duration_ms) AS p50, "
            "  quantile(0.95)(duration_ms) AS p95, "
            "  avg(length(payload)) AS avg_payload "
            "FROM workflow_audit "
            "WHERE workflow_id = %(workflow_id)s "
            "  AND event_type = 'workflow.complete' "
            "  AND created_at >= %(cutoff)s "
            "  AND duration_ms IS NOT NULL"
        )
        params: dict[str, Any] = {"workflow_id": workflow_id, "cutoff": cutoff}
        try:
            result = await client.query(sql, parameters=params)
            row = (
                result.result_rows[0] if getattr(result, "result_rows", None) else None
            )
        except Exception as exc:
            _logger.warning("CH query failed: %s", exc)
            row = None

        if not row or row[0] == 0:
            return CostEstimate(
                workflow_id=workflow_id,
                version=version,
                sample_size=0,
                p50_duration_ms=0.0,
                p95_duration_ms=0.0,
                estimated_storage_bytes=input_size_bytes,
            )

        sample_size = int(row[0])
        p50 = float(row[1] or 0.0)
        p95 = float(row[2] or 0.0)
        avg_payload = float(row[3] or 0.0)

        estimated_storage = int(avg_payload * sample_size + input_size_bytes)
        estimated_compute_seconds = p95 / 1000.0

        llm_breakdown: LLMCostBreakdown | None = None
        try:
            from src.backend.dsl.workflow.versioning import get_global_registry

            registry = get_global_registry()
            wf_version = registry.get_default(workflow_id)
            decl = getattr(wf_version, "declaration", None) if wf_version else None
            if decl is not None:
                llm_breakdown = self._estimate_llm_cost(decl, sample_size=sample_size)
        except Exception as _:
            llm_breakdown = None

        estimated_cost_usd = llm_breakdown.total_usd if llm_breakdown else Decimal("0")
        estimated_tokens = llm_breakdown.total_tokens if llm_breakdown else 0

        return CostEstimate(
            workflow_id=workflow_id,
            version=version,
            sample_size=sample_size,
            p50_duration_ms=p50,
            p95_duration_ms=p95,
            estimated_llm_tokens=estimated_tokens,
            estimated_cost_usd=estimated_cost_usd,
            estimated_compute_seconds=estimated_compute_seconds,
            estimated_storage_bytes=estimated_storage,
            llm_breakdown=llm_breakdown,
        )

    @staticmethod
    def _estimate_llm_cost(decl: Any, *, sample_size: int) -> LLMCostBreakdown | None:
        """Sprint 12 K4 W2 — оценка LLM-стоимости на основе activity-types.

        Сканирует ``decl.steps`` на activity с ``args.model_id`` (или
        ``function`` начинающийся с ``services.ai.``) и умножает на
        historical avg tokens × model price.
        """
        try:
            from src.backend.services.ai.costs.llm_model_pricing import LLMModelPricing
        except ImportError:
            return None

        pricing = LLMModelPricing()
        per_model: dict[str, Decimal] = {}
        total_tokens = 0

        steps = getattr(decl, "steps", []) or []
        for step in steps:
            if getattr(step, "type", None) != "activity":
                continue
            args = getattr(step, "args", {}) or {}
            model_id = args.get("model_id")
            tokens = int(args.get("estimated_tokens", 0))

            if not model_id and not args.get("function", "").startswith("services.ai."):
                continue

            model_name = model_id or "default-llm"
            tokens = tokens or 1000
            total_tokens += tokens

            price = pricing.get_price(model_name)
            cost = (Decimal(tokens) / Decimal(1000)) * price
            per_model[model_name] = per_model.get(model_name, Decimal("0")) + cost

        if not per_model:
            return None

        total_usd = sum(per_model.values(), Decimal("0"))
        return LLMCostBreakdown(
            per_model=per_model, total_usd=total_usd, total_tokens=total_tokens
        )
