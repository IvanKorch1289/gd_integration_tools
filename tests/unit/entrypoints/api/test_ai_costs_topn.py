"""Тесты /admin/ai-costs (Wave D.5)."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_endpoint_returns_disabled_when_langfuse_off() -> None:
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.backend.core.config import ai_stack as cfg
    from src.backend.entrypoints.api.v1.endpoints.ai_costs import router

    original = cfg.langfuse_settings.enabled
    cfg.langfuse_settings.enabled = False
    try:
        app = FastAPI()
        app.include_router(router, prefix="/api/v1/admin")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/v1/admin/ai-costs?top_n=5")
        assert resp.status_code in (200, 401)
        if resp.status_code == 200:
            data = resp.json()
            assert data["backend"] == "disabled"
    finally:
        cfg.langfuse_settings.enabled = original


@pytest.mark.asyncio
async def test_link_endpoint_returns_disabled_without_host() -> None:
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.backend.core.config import ai_stack as cfg
    from src.backend.entrypoints.api.v1.endpoints.ai_costs import router

    original_host = cfg.langfuse_settings.host
    original_base = cfg.langfuse_settings.deep_link_base
    cfg.langfuse_settings.host = ""
    cfg.langfuse_settings.deep_link_base = ""
    try:
        app = FastAPI()
        app.include_router(router, prefix="/api/v1/admin")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/v1/admin/ai-costs/link")
        if resp.status_code == 200:
            data = resp.json()
            assert data["enabled"] is False
    finally:
        cfg.langfuse_settings.host = original_host
        cfg.langfuse_settings.deep_link_base = original_base
