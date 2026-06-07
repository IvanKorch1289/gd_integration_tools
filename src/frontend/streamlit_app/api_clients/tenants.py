"""Tenants: список + детальный профиль (admin/tenants)."""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("TenantsClient",)


class TenantsClient(BaseAPIClient):
    """Клиент для admin/tenants endpoints (multi-tenancy, audit)."""

    def get_tenants(self) -> dict[str, Any]:
        """Список tenants с агрегатом по audit-events.

        GET /api/v1/admin/tenants
        При ClickHouse offline возвращает ``{"stub": True, "tenants": [], "total": 0}``.
        """
        return self._request("GET", "/api/v1/admin/tenants")

    def get_tenant_detail(self, tenant_id: str) -> dict[str, Any]:
        """Детальный профиль tenant'а (audit events, denials, RLS).

        GET /api/v1/admin/tenants/{tenant_id}
        При ClickHouse offline возвращает ``{"stub": True, ...}``.
        """
        return self._request("GET", f"/api/v1/admin/tenants/{tenant_id}")
