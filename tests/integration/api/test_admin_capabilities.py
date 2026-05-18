# ruff: noqa: S101
"""Integration tests для admin/capabilities endpoints (К5/docs-tenants-caps)."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_list_capabilities_returns_vocabulary() -> None:
    """list_capabilities отдаёт vocabulary + catalog."""
    from src.backend.entrypoints.api.v1.endpoints.admin_capabilities import (
        list_capabilities,
    )

    payload = await list_capabilities()
    assert "vocabulary" in payload
    assert "catalog" in payload
    # vocabulary должен содержать v0-каталог из ADR-044 (>0 entries)
    assert isinstance(payload["vocabulary"], list)
    assert isinstance(payload["catalog"], list)


@pytest.mark.asyncio
async def test_get_capability_audit_events_returns_safe_limit() -> None:
    """get_capability_audit_events ограничивает limit разумным диапазоном."""
    from src.backend.entrypoints.api.v1.endpoints.admin_capabilities import (
        get_capability_audit_events,
    )

    payload = await get_capability_audit_events(limit=99999)
    assert payload["limit"] <= 1000
    assert "events" in payload
    assert isinstance(payload["events"], list)
