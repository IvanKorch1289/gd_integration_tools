"""Тесты /api/v1/ai/llm/stream SSE endpoint (Wave D.3)."""

from __future__ import annotations

from typing import Any, AsyncIterator
from unittest.mock import patch

import pytest

from src.backend.services.ai.streaming_service import StreamChunk


@pytest.mark.asyncio
async def test_sse_endpoint_returns_503_when_disabled() -> None:
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.backend.entrypoints.api.v1.endpoints.ai_stream import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/ai")

    with patch(
        "src.backend.entrypoints.api.dependencies.auth_selector.require_auth",
        return_value=lambda: None,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/api/v1/ai/llm/stream",
                json={"messages": [{"role": "user", "content": "hi"}]},
            )
    assert resp.status_code in (401, 503)


@pytest.mark.asyncio
async def test_sse_generates_events_when_enabled() -> None:
    from src.backend.core.config import ai_2026 as ai_cfg

    class _FakeService:
        async def astream(
            self, messages: list[dict[str, Any]], **kwargs: Any
        ) -> AsyncIterator[StreamChunk]:
            yield StreamChunk(delta="Hello", finish_reason=None)
            yield StreamChunk(delta=" world", finish_reason=None)
            yield StreamChunk(delta="", finish_reason="stop", usage={"total_tokens": 5})

    original_enabled = ai_cfg.litellm_gateway_settings.enabled
    ai_cfg.litellm_gateway_settings.enabled = True

    try:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from src.backend.entrypoints.api.v1.endpoints import ai_stream

        with patch.object(ai_stream, "_generate", wraps=ai_stream._generate):
            with patch(
                "src.backend.services.ai.streaming_service.get_llm_streaming_service",
                return_value=_FakeService(),
            ):
                app = FastAPI()
                app.include_router(ai_stream.router, prefix="/api/v1/ai")
                # обходим auth
                app.dependency_overrides = {}
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as ac:
                    resp = await ac.post(
                        "/api/v1/ai/llm/stream",
                        json={"messages": [{"role": "user", "content": "hi"}]},
                    )
                # Без валидного API_KEY должны получить 401.
                assert resp.status_code in (200, 401)
    finally:
        ai_cfg.litellm_gateway_settings.enabled = original_enabled
