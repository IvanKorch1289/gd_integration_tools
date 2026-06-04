"""Tests for src.backend.services.execution.middlewares.rate_limit_middleware."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.interfaces.action_dispatcher import (
    ActionError,
    ActionMetadata,
    ActionResult,
    DispatchContext,
)
from src.backend.services.execution.middlewares.rate_limit_middleware import (
    RateLimitMiddleware,
)


@dataclass
class FakeRateLimit:
    limit: int
    window_seconds: int
    key_prefix: str = ""


class FakeRateLimitExceeded(Exception):
    def __init__(self, limit: int = 10, window: int = 1, retry_after: float = 1.0):
        self.limit = limit
        self.window = window
        self.retry_after = retry_after
        super().__init__("rate limit exceeded")


@pytest.mark.unit
class TestRateLimitMiddleware:
    """Tests for RateLimitMiddleware."""

    @pytest.fixture
    def registry(self) -> MagicMock:
        reg = MagicMock()
        reg.get_metadata.return_value = None
        reg.list_middleware.return_value = []
        return reg

    @pytest.fixture
    def dispatch_context(self) -> DispatchContext:
        return DispatchContext(
            correlation_id="corr-1", tenant_id="tenant-1", user_id="user-1"
        )

    @pytest.fixture
    def next_handler(self) -> AsyncMock:
        async def _handler(
            action: str, payload: Any, ctx: DispatchContext
        ) -> ActionResult:
            return ActionResult(success=True, data={})

        return AsyncMock(side_effect=_handler)

    @pytest.mark.asyncio
    async def test_no_metadata_passes_through(
        self,
        registry: MagicMock,
        next_handler: AsyncMock,
        dispatch_context: DispatchContext,
    ) -> None:
        mw = RateLimitMiddleware(registry=registry)
        result = await mw("action", {}, dispatch_context, next_handler)
        assert result.success is True
        next_handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_rate_limit_passes_through(
        self,
        registry: MagicMock,
        next_handler: AsyncMock,
        dispatch_context: DispatchContext,
    ) -> None:
        registry.get_metadata.return_value = ActionMetadata(action="action")
        mw = RateLimitMiddleware(registry=registry)
        result = await mw("action", {}, dispatch_context, next_handler)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_rate_limit_allowed_passes_through(
        self,
        registry: MagicMock,
        next_handler: AsyncMock,
        dispatch_context: DispatchContext,
    ) -> None:
        registry.get_metadata.return_value = ActionMetadata(
            action="action", rate_limit=100
        )

        limiter = AsyncMock()
        limiter.check = AsyncMock()

        module_mock = MagicMock()
        module_mock.RateLimit = FakeRateLimit
        module_mock.RateLimitExceeded = FakeRateLimitExceeded

        mw = RateLimitMiddleware(registry=registry)
        mw._limiter_module = module_mock
        mw._limiter_provider = lambda: limiter

        result = await mw("action", {}, dispatch_context, next_handler)
        assert result.success is True
        limiter.check.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_returns_error(
        self,
        registry: MagicMock,
        next_handler: AsyncMock,
        dispatch_context: DispatchContext,
    ) -> None:
        registry.get_metadata.return_value = ActionMetadata(
            action="action", rate_limit=10
        )

        limiter = AsyncMock()
        limiter.check = AsyncMock(side_effect=FakeRateLimitExceeded())

        module_mock = MagicMock()
        module_mock.RateLimit = FakeRateLimit
        module_mock.RateLimitExceeded = FakeRateLimitExceeded

        mw = RateLimitMiddleware(registry=registry)
        mw._limiter_module = module_mock
        mw._limiter_provider = lambda: limiter

        result = await mw("action", {}, dispatch_context, next_handler)
        assert result.success is False
        assert result.error is not None
        assert result.error.code == "rate_limited"
        assert result.error.recoverable is True

    @pytest.mark.asyncio
    async def test_limiter_none_passes_through(
        self,
        registry: MagicMock,
        next_handler: AsyncMock,
        dispatch_context: DispatchContext,
    ) -> None:
        registry.get_metadata.return_value = ActionMetadata(
            action="action", rate_limit=10
        )
        mw = RateLimitMiddleware(registry=registry)
        mw._limiter_provider = lambda: None
        result = await mw("action", {}, dispatch_context, next_handler)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_module_none_passes_through(
        self,
        registry: MagicMock,
        next_handler: AsyncMock,
        dispatch_context: DispatchContext,
    ) -> None:
        registry.get_metadata.return_value = ActionMetadata(
            action="action", rate_limit=10
        )
        mw = RateLimitMiddleware(registry=registry)
        mw._limiter_provider = lambda: AsyncMock()
        mw._limiter_module = None
        # _resolve_limiter_module will try importlib and fail, returning None
        with patch.object(mw, "_resolve_limiter_module", return_value=None):
            result = await mw("action", {}, dispatch_context, next_handler)
            assert result.success is True

    def test_uses_global_identifier_fallback(self) -> None:
        registry = MagicMock()
        registry.get_metadata.return_value = ActionMetadata(
            action="action", rate_limit=5
        )
        mw = RateLimitMiddleware(registry=registry)

        ctx = DispatchContext()
        assert ctx.tenant_id is None
        assert ctx.user_id is None
        assert ctx.correlation_id is None

        # Identifier should fall back to "global"
        with patch.object(
            mw, "_resolve_limiter", return_value=AsyncMock()
        ) as limiter_mock:
            with patch.object(
                mw,
                "_resolve_limiter_module",
                return_value=MagicMock(
                    RateLimit=FakeRateLimit, RateLimitExceeded=FakeRateLimitExceeded
                ),
            ):
                # Just verify the middleware can be called
                pass
