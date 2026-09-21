"""Tests for src.backend.services.execution.middlewares.audit_middleware."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.core.interfaces.action_dispatcher import ActionResult, DispatchContext
from src.backend.services.execution.middlewares.audit_middleware import AuditMiddleware


@pytest.mark.unit
class TestAuditMiddleware:
    """Tests for AuditMiddleware."""

    @pytest.fixture
    def middleware(self) -> AuditMiddleware:
        return AuditMiddleware()

    @pytest.fixture
    def dispatch_context(self) -> DispatchContext:
        return DispatchContext(
            correlation_id="corr-1", tenant_id="tenant-1", source="test"
        )

    @pytest.fixture
    def next_handler(self) -> AsyncMock:
        async def _handler(
            action: str, payload: Any, ctx: DispatchContext
        ) -> ActionResult:
            return ActionResult(success=True, data={"ok": True})

        return AsyncMock(side_effect=_handler)

    @pytest.mark.asyncio
    async def test_logs_start_and_end(
        self,
        middleware: AuditMiddleware,
        next_handler: AsyncMock,
        dispatch_context: DispatchContext,
    ) -> None:
        with patch(
            "src.backend.services.execution.middlewares.audit_middleware._logger"
        ) as mock_logger:
            result = await middleware("test_action", {}, dispatch_context, next_handler)
            assert result.success is True
            assert mock_logger.info.call_count == 2
            # First call is start, second is end
            start_call = mock_logger.info.call_args_list[0]
            assert start_call[0][0] == "action.dispatch.start"
            end_call = mock_logger.info.call_args_list[1]
            assert end_call[0][0] == "action.dispatch.end"

    @pytest.mark.asyncio
    async def test_logs_error_on_exception(
        self, middleware: AuditMiddleware, dispatch_context: DispatchContext
    ) -> None:
        async def failing_handler(
            action: str, payload: Any, ctx: DispatchContext
        ) -> ActionResult:
            raise ValueError("boom")

        with patch(
            "src.backend.services.execution.middlewares.audit_middleware._logger"
        ) as mock_logger:
            with pytest.raises(ValueError, match="boom"):
                await middleware("test_action", {}, dispatch_context, failing_handler)
            assert any(
                call[0][0] == "action.dispatch.error"
                for call in mock_logger.exception.call_args_list
            )

    @pytest.mark.asyncio
    async def test_end_log_includes_duration(
        self,
        middleware: AuditMiddleware,
        next_handler: AsyncMock,
        dispatch_context: DispatchContext,
    ) -> None:
        with patch(
            "src.backend.services.execution.middlewares.audit_middleware._logger"
        ) as mock_logger:
            await middleware("test_action", {}, dispatch_context, next_handler)
            end_call = mock_logger.info.call_args_list[1]
            extra = end_call.kwargs.get("extra") or end_call[1].get("extra")
            assert extra is not None
            assert "duration_ms" in extra
            assert extra["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_end_log_includes_error_code_on_failure(
        self, middleware: AuditMiddleware, dispatch_context: DispatchContext
    ) -> None:
        from src.backend.core.interfaces.action_dispatcher import ActionError

        async def failing_result(
            action: str, payload: Any, ctx: DispatchContext
        ) -> ActionResult:
            return ActionResult(
                success=False, error=ActionError(code="ERR_1", message="oops")
            )

        with patch(
            "src.backend.services.execution.middlewares.audit_middleware._logger"
        ) as mock_logger:
            await middleware("test_action", {}, dispatch_context, failing_result)
            end_call = mock_logger.info.call_args_list[1]
            extra = end_call.kwargs.get("extra") or end_call[1].get("extra")
            assert extra["error_code"] == "ERR_1"

    @pytest.mark.asyncio
    async def test_passes_action_payload_context_to_next(
        self,
        middleware: AuditMiddleware,
        next_handler: AsyncMock,
        dispatch_context: DispatchContext,
    ) -> None:
        await middleware("my_action", {"key": "val"}, dispatch_context, next_handler)
        next_handler.assert_awaited_once_with(
            "my_action", {"key": "val"}, dispatch_context
        )
