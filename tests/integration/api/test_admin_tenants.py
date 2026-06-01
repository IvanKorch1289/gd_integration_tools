# ruff: noqa: S101
"""Integration tests для admin/tenants endpoints (К5/docs-tenants-caps)."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_list_tenants_returns_stub_payload() -> None:
    """list_tenants отдаёт stub-структуру с пустым списком."""
    from src.backend.entrypoints.api.v1.endpoints.admin_tenants import list_tenants

    payload = await list_tenants()
    assert "tenants" in payload
    assert payload["total"] == 0
    assert payload.get("stub") is True


@pytest.mark.asyncio
async def test_get_tenant_detail_returns_basic_structure() -> None:
    """get_tenant_detail возвращает базовую структуру без падений."""
    from src.backend.entrypoints.api.v1.endpoints.admin_tenants import get_tenant_detail

    payload = await get_tenant_detail("acme")
    assert payload["tenant_id"] == "acme"
    assert "quotas" in payload
    assert "rls_state" in payload
    assert "audit_events_recent" in payload
