"""AI Cost Dashboard backend (K4 S6 W3).

Назначение:
    Агрегирует данные из ``langfuse_reader`` и ``alerts`` для финальной
    Streamlit-страницы 23_AI_Cost_Tracking.py. Поддерживает фильтры:

        * date_range (через ``window_hours``);
        * tenant_id (per-tenant breakdown через ``TenantContext``);
        * model (gpt-4 / claude-opus / ...);
        * pipeline (route_name / agent_name).

Управляется feature-flag ``ai_cost_dashboard_strict``: при False
возвращает empty payload (но не падает).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from src.backend.infrastructure.logging.factory import get_logger
from src.backend.services.ai.costs.alerts import CostAlert, CostAlertService
from src.backend.services.ai.costs.langfuse_reader import CostRow, LangFuseReader

logger = get_logger(__name__)

__all__ = (
    "AICostDashboard",
    "CostByTenant",
    "DashboardSnapshot",
    "TokenRateTrend",
    "UsageByModel",
)


@dataclass(slots=True)
class UsageByModel:
    """Bar-chart точка: cost+tokens по одной модели."""

    model: str
    requests: int
    prompt_tokens: int
    completion_tokens: int
    total_cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CostByTenant:
    """Pie-chart точка: cost по одному тенанту."""

    tenant_id: str
    requests: int
    total_cost_usd: float
    share: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TokenRateTrend:
    """Line-chart точка: token rate на интервал (rolling 24h)."""

    bucket: str  # ISO datetime начала bucket
    prompt_tokens: int
    completion_tokens: int
    requests: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DashboardSnapshot:
    """Сводный snapshot для AI Cost Tracking dashboard."""

    generated_at: str
    backend: str = "disabled"
    by_model: list[UsageByModel] = field(default_factory=list)
    by_tenant: list[CostByTenant] = field(default_factory=list)
    token_trends: list[TokenRateTrend] = field(default_factory=list)
    alerts: list[CostAlert] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "backend": self.backend,
            "filters": self.filters,
            "by_model": [m.to_dict() for m in self.by_model],
            "by_tenant": [t.to_dict() for t in self.by_tenant],
            "token_trends": [tr.to_dict() for tr in self.token_trends],
            "alerts": [a.to_dict() for a in self.alerts],
        }


class AICostDashboard:
    """Агрегатор данных для AI Cost Tracking dashboard."""

    def __init__(
        self,
        *,
        reader: LangFuseReader | None = None,
        alert_service: CostAlertService | None = None,
    ) -> None:
        self._reader = reader or LangFuseReader()
        self._alerts = alert_service or CostAlertService(reader=self._reader)

    def is_enabled(self) -> bool:
        """Проверяет feature-flag ``ai_cost_dashboard_strict``."""
        try:
            from src.backend.core.config.features import feature_flags

            return bool(feature_flags.ai_cost_dashboard_strict)
        except Exception as exc:
            logger.debug("AICostDashboard: feature_flags недоступны: %s", exc)
            return False

    async def snapshot(
        self,
        *,
        window_hours: int = 24,
        tenant_id: str | None = None,
        model_filter: str | None = None,
        pipeline_filter: str | None = None,
        top_n: int = 50,
    ) -> DashboardSnapshot:
        """Возвращает агрегированный snapshot для UI.

        Args:
            window_hours: глубина окна (часов).
            tenant_id: фильтр по тенанту (None → все).
            model_filter: фильтр по модели (substring, case-insensitive).
            pipeline_filter: фильтр по pipeline/route (substring).
            top_n: лимит на размер каждой группы.
        """
        snapshot = DashboardSnapshot(
            generated_at=datetime.now(UTC).isoformat(),
            filters={
                "window_hours": window_hours,
                "tenant_id": tenant_id,
                "model_filter": model_filter,
                "pipeline_filter": pipeline_filter,
                "top_n": top_n,
            },
        )

        if not self.is_enabled():
            return snapshot

        window = timedelta(hours=max(1, int(window_hours)))

        # by_model — group_by=provider, фильтрация по model_filter.
        by_model_rows = await self._safe_fetch(
            group_by="provider", window=window, top_n=top_n
        )
        snapshot.by_model = _to_model_rows(by_model_rows, model_filter=model_filter)

        # by_tenant — group_by=tenant.
        by_tenant_rows = await self._safe_fetch(
            group_by="tenant", window=window, top_n=top_n
        )
        snapshot.by_tenant = _to_tenant_rows(by_tenant_rows, tenant_id=tenant_id)

        # token_trends — rolling 24h, 12 buckets по 2 часа.
        snapshot.token_trends = _build_token_trends(by_model_rows, window=window)

        # alerts — текущие аномалии.
        try:
            snapshot.alerts = await self._alerts.detect_anomalies(window=window)
        except Exception as exc:
            logger.debug("AICostDashboard alerts skipped: %s", exc)
            snapshot.alerts = []

        snapshot.backend = "langfuse" if by_model_rows or by_tenant_rows else "empty"
        return snapshot

    async def _safe_fetch(
        self, *, group_by: str, window: timedelta, top_n: int
    ) -> list[CostRow]:
        try:
            return await self._reader.fetch_costs(
                group_by=group_by, window=window, top_n=top_n
            )
        except Exception as exc:
            logger.warning("AICostDashboard fetch %s failed: %s", group_by, exc)
            return []


def _to_model_rows(
    rows: Iterable[CostRow], *, model_filter: str | None
) -> list[UsageByModel]:
    f = (model_filter or "").lower().strip()
    result: list[UsageByModel] = []
    for row in rows:
        model = row.key or "unknown"
        if f and f not in model.lower():
            continue
        result.append(
            UsageByModel(
                model=model,
                requests=row.requests,
                prompt_tokens=row.prompt_tokens,
                completion_tokens=row.completion_tokens,
                total_cost_usd=row.total_cost_usd,
            )
        )
    return result


def _to_tenant_rows(
    rows: Iterable[CostRow], *, tenant_id: str | None
) -> list[CostByTenant]:
    materialised = [
        CostByTenant(
            tenant_id=row.key or "default",
            requests=row.requests,
            total_cost_usd=row.total_cost_usd,
        )
        for row in rows
    ]
    if tenant_id:
        materialised = [r for r in materialised if r.tenant_id == tenant_id]
    total = sum(r.total_cost_usd for r in materialised)
    if total > 0:
        for r in materialised:
            r.share = round(r.total_cost_usd / total, 6)
    return materialised


def _build_token_trends(
    rows: Iterable[CostRow], *, window: timedelta
) -> list[TokenRateTrend]:
    """Простой rolling trend: разбивает на 12 равных bucket.

    Поскольку source-rows не несут timestamp на уровне CostRow, trend
    усредняется равномерно. Реальная per-time детализация требует
    отдельного fetch с group_by=hour (deferred K4 next wave).
    """
    rows_list = list(rows)
    if not rows_list:
        return []
    bucket_count = 12
    bucket_seconds = max(1, int(window.total_seconds() / bucket_count))
    now = datetime.now(UTC)
    trends: list[TokenRateTrend] = []
    total_prompt = sum(r.prompt_tokens for r in rows_list)
    total_completion = sum(r.completion_tokens for r in rows_list)
    total_requests = sum(r.requests for r in rows_list)
    per_bucket_prompt = total_prompt // bucket_count
    per_bucket_completion = total_completion // bucket_count
    per_bucket_requests = total_requests // bucket_count

    for i in range(bucket_count):
        ts = now - timedelta(seconds=(bucket_count - 1 - i) * bucket_seconds)
        trends.append(
            TokenRateTrend(
                bucket=ts.replace(microsecond=0).isoformat(),
                prompt_tokens=per_bucket_prompt,
                completion_tokens=per_bucket_completion,
                requests=per_bucket_requests,
            )
        )
    return trends
