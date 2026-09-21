"""Tests for src.backend.services.execution.middlewares.idempotency_middleware."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.core.interfaces.action_dispatcher import ActionResult, DispatchContext
from src.backend.services.execution.middlewares.idempotency_middleware import (
    IdempotencyMiddleware,
)


class TestIdempotencyMiddleware:
    @pytest.fixture
    def middleware(self) -> IdempotencyMiddleware:
        return IdempotencyMiddleware()

    @pytest.fixture
    def context(self) -> DispatchContext:
        return DispatchContext(correlation_id="c1", tenant_id="t1", source="test")

    @pytest.mark.asyncio
    async def test_no_key_passes_through(
        self, middleware: IdempotencyMiddleware, context: DispatchContext
    ) -> None:
        next_handler = AsyncMock(return_value=ActionResult(success=True, data={}))
        result = await middleware("act", {}, context, next_handler)
        assert result.success is True
        next_handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cached_result_returned(
        self, middleware: IdempotencyMiddleware, context: DispatchContext
    ) -> None:
        context.idempotency_key = "key1"
        cached = ActionResult(success=True, data={"cached": True})
        await middleware._store.set("act::key1", cached)
        next_handler = AsyncMock()
        result = await middleware("act", {}, context, next_handler)
        assert result.success is True
        assert result.metadata.get("cached") is True
        next_handler.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_success_caches_result(
        self, middleware: IdempotencyMiddleware, context: DispatchContext
    ) -> None:
        context.idempotency_key = "key2"
        next_handler = AsyncMock(
            return_value=ActionResult(success=True, data={"ok": True})
        )
        result = await middleware("act", {}, context, next_handler)
        assert result.success is True
        cached = await middleware._store.get("act::key2")
        assert cached is not None

    @pytest.mark.asyncio
    async def test_failure_not_cached(
        self, middleware: IdempotencyMiddleware, context: DispatchContext
    ) -> None:
        context.idempotency_key = "key3"
        next_handler = AsyncMock(return_value=ActionResult(success=False, error=None))
        result = await middleware("act", {}, context, next_handler)
        assert result.success is False
        cached = await middleware._store.get("act::key3")
        assert cached is None
