"""REST API планировщика webhook'ов (ADR-0432).

Endpoints:

* ``GET /api/v1/webhooks/scheduled`` — список запланированных webhook'ов
  тенанта (Redis-backed, TTL 7 дней);
* ``POST /api/v1/webhook/schedule`` — запланировать webhook (один раз через
  ``delay_seconds`` либо по ``cron``).

Безопасность: URL проходит SSRF-guard :func:`assert_safe_url` (только
http/https, без private/loopback/link-local адресов) — иначе планировщик
стал бы вектором запросов во внутреннюю сеть.

Авторизация: admin-роль (``OPERATOR`` / ``SUPER_ADMIN``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.backend.core.auth.admin_roles import AdminRole, require_admin
from src.backend.core.logging import get_logger

__all__ = ("router",)

logger = get_logger("entrypoints.webhook_scheduler")

_ADMIN_GUARD = Depends(require_admin((AdminRole.OPERATOR, AdminRole.SUPER_ADMIN)))

router = APIRouter(dependencies=[_ADMIN_GUARD])


class WebhookScheduleRequest(BaseModel):
    """Запрос на планирование webhook'а."""

    url: str = Field(min_length=1, description="Целевой URL (http/https).")
    payload: dict[str, Any] = Field(default_factory=dict)
    cron: str | None = Field(default=None, description="Cron-выражение (минуты).")
    delay_seconds: int | None = Field(default=None, ge=1, le=86400)
    headers: dict[str, str] = Field(default_factory=dict)


@router.get(
    "/webhooks/scheduled",
    summary="Запланированные webhook'и",
    description="Список отложенных/периодических webhook'ов тенанта.",
    tags=["Webhooks"],
    responses={200: {"description": "Список запланированных webhook'ов."}},
)
async def list_scheduled_webhooks(
    tenant_id: str = Query(default="", description="Тенант-владелец."),
) -> list[dict[str, Any]]:
    """Список запланированных webhook'ов."""
    from src.backend.core.di.providers.webhooks import get_webhook_scheduler_provider

    scheduler = get_webhook_scheduler_provider()
    return await scheduler.list_scheduled(tenant_id=tenant_id)


@router.post(
    "/webhook/schedule",
    summary="Запланировать webhook",
    description=(
        "Планирует однократную (delay_seconds) или периодическую (cron) "
        "доставку webhook'а. URL проверяется SSRF-guard'ом."
    ),
    tags=["Webhooks"],
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Webhook запланирован."},
        400: {"description": "URL отклонён SSRF-guard'ом / некорректный cron."},
    },
)
async def schedule_webhook(
    request: WebhookScheduleRequest,
    tenant_id: str = Query(default="", description="Тенант-владелец."),
) -> dict[str, Any]:
    """Запланировать webhook'а."""
    from src.backend.core.di.providers.webhooks import get_webhook_scheduler_provider
    from src.backend.core.net.url_guard import UrlNotAllowedError, assert_safe_url

    try:
        assert_safe_url(request.url)
    except UrlNotAllowedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"URL отклонён: {exc}"
        ) from exc

    scheduler = get_webhook_scheduler_provider()
    try:
        schedule_id = await scheduler.schedule(
            request.url,
            request.payload,
            cron=request.cron,
            delay_seconds=request.delay_seconds,
            headers=request.headers,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.warning("webhook schedule failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Планировщик webhook'ов недоступен (Redis?)",
        ) from exc
    return {"schedule_id": schedule_id, "status": "scheduled"}
