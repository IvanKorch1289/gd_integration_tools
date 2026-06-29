"""Admin endpoint: GET /admin/certs/expiring (S171 M21, D256).

Возвращает список сертификатов, истекающих в течение N дней.
Используется для мониторинга и pre-emptive rotation.

Pattern (D256, Ponytail): thin wrapper над CertStore.list_expiring.
Production: integration с Prometheus alert (DEFER M21+).
"""
# ruff: noqa: E501
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from src.backend.core.logging import get_logger

logger = get_logger(__name__)

__all__ = (
    "router",
    "CertExpiringItem",
    "EXPIRING_DEFAULT_DAYS",
    "EXPIRING_MAX_DAYS",
)

router = APIRouter(prefix="/admin/certs", tags=["admin", "certs"])

EXPIRING_DEFAULT_DAYS = 30
EXPIRING_MAX_DAYS = 365


class CertExpiringItem(BaseModel):
    """Один сертификат в списке expiring (D256 response format)."""

    cert_id: str = Field(..., description="ID сертификата (filename без расширения).")
    expires_at: datetime = Field(..., description="Когда истекает.")
    days_remaining: int = Field(..., description="Дней до истечения.")


class CertExpiringListResponse(BaseModel):
    """Response для GET /admin/certs/expiring."""

    days_window: int
    total: int
    items: list[CertExpiringItem]


@router.get("/expiring", response_model=CertExpiringListResponse)
async def list_expiring_certs(
    days: int = Query(
        default=EXPIRING_DEFAULT_DAYS,
        ge=1,
        le=EXPIRING_MAX_DAYS,
        description="Окно в днях для поиска истекающих сертификатов.",
    ),
    cert_store: Any = None,
) -> CertExpiringListResponse:
    """GET /admin/certs/expiring?days=30.

    Returns:
        Список истекающих сертификатов + метаданные.
    """
    if cert_store is None:
        from src.backend.core.config.cert_store import cert_store_settings
        from src.backend.infrastructure.security.cert_store import CertStore

        cert_store = CertStore.from_settings(cert_store_settings)

    now = datetime.now(timezone.utc)
    before = now + timedelta(days=days)
    entries = await cert_store._backend.list_expiring(before=before)

    items: list[CertExpiringItem] = []
    for entry in entries:
        exp = getattr(entry, "expires_at", None)
        if exp is None:
            continue
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        days_remaining = (exp - now).days
        sid = getattr(entry, "service_id", None)
        items.append(
            CertExpiringItem(
                cert_id=sid if sid is not None else "",
                expires_at=exp,
                days_remaining=days_remaining,
            )
        )

    items.sort(key=lambda x: x.days_remaining)

    logger.info(
        "admin.certs.list_expiring days=%d total=%d",
        days, len(items),
    )
    return CertExpiringListResponse(
        days_window=days,
        total=len(items),
        items=items,
    )
