"""Admin workflow cost estimation endpoints — Sprint 12 K3 W3 + K4 W2.

Endpoints (mount /api/v1/admin/workflow-cost):

* ``POST /estimate`` — pre-run estimate;
* ``GET /history/{workflow_id}`` — historical runs (p50/p95 + total cost).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

__all__ = ("router",)

router = APIRouter(prefix="/admin/workflow-cost", tags=["admin", "workflow", "cost"])


class CostEstimateRequest(BaseModel):
    """Запрос на pre-run cost estimation."""

    workflow_id: str = Field(min_length=1, max_length=120)
    version: str | None = None
    input_size_bytes: int = Field(default=0, ge=0)
    sample_period_days: int = Field(default=30, ge=1, le=365)


class LLMCostBreakdownResponse(BaseModel):
    """LLM breakdown по моделям."""

    per_model: dict[str, str] = Field(default_factory=dict)
    total_usd: str
    total_tokens: int


class CostEstimateResponse(BaseModel):
    """Ответ pre-run estimate."""

    workflow_id: str
    version: str | None = None
    sample_size: int
    p50_duration_ms: float
    p95_duration_ms: float
    estimated_llm_tokens: int = 0
    estimated_cost_usd: str
    estimated_compute_seconds: float
    estimated_storage_bytes: int
    llm_breakdown: LLMCostBreakdownResponse | None = None


def _serialize_decimal(value: Decimal) -> str:
    return f"{value:.6f}"


@router.post("/estimate", response_model=CostEstimateResponse)
async def estimate_workflow_cost(request: CostEstimateRequest) -> CostEstimateResponse:
    """Sprint 12 K3 W3 — pre-run estimation для workflow."""
    from src.backend.services.workflows.cost_estimator import WorkflowCostEstimator

    estimator = WorkflowCostEstimator()
    estimate = await estimator.estimate(
        workflow_id=request.workflow_id,
        version=request.version,
        input_size_bytes=request.input_size_bytes,
        sample_period_days=request.sample_period_days,
    )

    llm_breakdown_resp: LLMCostBreakdownResponse | None = None
    if estimate.llm_breakdown is not None:
        llm_breakdown_resp = LLMCostBreakdownResponse(
            per_model={
                k: _serialize_decimal(v)
                for k, v in estimate.llm_breakdown.per_model.items()
            },
            total_usd=_serialize_decimal(estimate.llm_breakdown.total_usd),
            total_tokens=estimate.llm_breakdown.total_tokens,
        )

    return CostEstimateResponse(
        workflow_id=estimate.workflow_id,
        version=estimate.version,
        sample_size=estimate.sample_size,
        p50_duration_ms=estimate.p50_duration_ms,
        p95_duration_ms=estimate.p95_duration_ms,
        estimated_llm_tokens=estimate.estimated_llm_tokens,
        estimated_cost_usd=_serialize_decimal(estimate.estimated_cost_usd),
        estimated_compute_seconds=estimate.estimated_compute_seconds,
        estimated_storage_bytes=estimate.estimated_storage_bytes,
        llm_breakdown=llm_breakdown_resp,
    )


@router.get("/history/{workflow_id}")
async def get_workflow_cost_history(
    workflow_id: str, period_days: int = Query(7, ge=1, le=90)
) -> dict[str, Any]:
    """Историческая стоимость workflow за период (для page 15 trend)."""
    from datetime import datetime, timedelta, timezone

    try:
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
        client = await get_async_client(host=host, port=port, database=database)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ClickHouse unavailable: {exc}",
        ) from exc

    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
    try:
        result = await client.query(
            "SELECT toDate(created_at) AS day, "
            "  count() AS runs, "
            "  quantile(0.95)(duration_ms) AS p95 "
            "FROM workflow_audit "
            "WHERE workflow_id = %(workflow_id)s "
            "  AND event_type = 'workflow.complete' "
            "  AND created_at >= %(cutoff)s "
            "GROUP BY day ORDER BY day",
            parameters={"workflow_id": workflow_id, "cutoff": cutoff},
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ClickHouse query failed: {exc}",
        ) from exc

    series: list[dict[str, Any]] = []
    for row in getattr(result, "result_rows", []):
        series.append(
            {"day": str(row[0]), "runs": int(row[1]), "p95_ms": float(row[2] or 0.0)}
        )
    return {"workflow_id": workflow_id, "period_days": period_days, "series": series}
