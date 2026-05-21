"""AI cost-dashboard REST endpoints (Wave D.5).

* ``GET /admin/ai-costs`` — топ-N по group_by (route/tenant/provider).
* ``GET /admin/ai-costs/alerts`` — обнаруженные аномалии cost.

Backend: LangFuse (primary при ``LANGFUSE_ENABLED=true``). При
выключенном LangFuse возвращает пустой список + ``backend=disabled`` —
рассматривается как deprecated transition period.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from src.backend.entrypoints.api.dependencies.auth_selector import (
    AuthMethod,
    require_auth,
)

__all__ = ("router",)

router = APIRouter()


@router.get(
    "/ai-costs",
    summary="Cost-аналитика (LangFuse primary, ClickHouse fallback deprecated)",
    dependencies=[Depends(require_auth([AuthMethod.API_KEY, AuthMethod.JWT]))],
)
async def get_ai_costs(
    top_n: int = Query(default=10, ge=1, le=200),
    group_by: Literal["route", "tenant", "provider"] = Query(default="route"),
    window_hours: int = Query(default=24, ge=1, le=24 * 30),
) -> dict[str, Any]:
    """Возвращает топ-N cost-строк через LangFuseReader."""
    from src.backend.core.config.ai_2026 import langfuse_settings
    from src.backend.services.ai.costs.langfuse_reader import LangFuseReader

    if not langfuse_settings.enabled:
        return {"backend": "disabled", "items": [], "count": 0}

    reader = LangFuseReader()
    rows = await reader.fetch_costs(
        window=timedelta(hours=window_hours), group_by=group_by, top_n=top_n
    )
    return {
        "backend": "langfuse",
        "group_by": group_by,
        "window_hours": window_hours,
        "items": [r.to_dict() for r in rows],
        "count": len(rows),
    }


@router.get(
    "/ai-costs/alerts",
    summary="Cost-аномалии (mean+2σ)",
    dependencies=[Depends(require_auth([AuthMethod.API_KEY, AuthMethod.JWT]))],
)
async def get_ai_cost_alerts(
    window_minutes: int = Query(default=60, ge=5, le=60 * 24),
    group_by: Literal["route", "tenant", "provider"] = Query(default="route"),
) -> dict[str, Any]:
    """Возвращает аномалии cost за окно ``window_minutes``."""
    from src.backend.core.config.ai_2026 import langfuse_settings
    from src.backend.services.ai.costs.alerts import CostAlertService

    if not langfuse_settings.enabled:
        return {"backend": "disabled", "alerts": [], "count": 0}

    service = CostAlertService()
    alerts = await service.detect_anomalies(
        window=timedelta(minutes=window_minutes), group_by=group_by
    )
    return {
        "backend": "langfuse",
        "alerts": [a.to_dict() for a in alerts],
        "count": len(alerts),
    }


@router.get(
    "/ai-costs/link",
    summary="Deep-link в LangFuse UI",
    dependencies=[Depends(require_auth([AuthMethod.API_KEY, AuthMethod.JWT]))],
)
async def get_langfuse_deeplink() -> dict[str, Any]:
    """Возвращает deep-link на LangFuse Web UI (для embed/sidebar)."""
    from src.backend.core.config.ai_2026 import langfuse_settings

    base = (langfuse_settings.deep_link_base or langfuse_settings.host or "").rstrip(
        "/"
    )
    if not base:
        return {"url": None, "enabled": False}
    return {"url": f"{base}/traces", "enabled": True}
