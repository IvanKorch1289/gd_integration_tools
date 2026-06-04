"""Unit tests for _AuditContext and _emit_wrapper.

Covers: construction, _emit, _emit_guard, _emit_final with/without audit_service.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.ai.gateway_audit_mixin import _AuditContext, _emit_wrapper
from src.backend.core.ai.gateway_models import AIRequest, AIResponse
from src.backend.core.ai.errors import GuardResult


class TestAuditContext:
    """Tests for :class:`_AuditContext`."""

    @pytest.fixture
    def request_obj(self) -> AIRequest:
        return AIRequest(workflow_id="wf1", tenant_id="t1", correlation_id="c1")

    @pytest.mark.asyncio
    async def test_emit_uses_audit_service(self, request_obj: AIRequest) -> None:
        """_emit delegates to audit_service.emit when provided."""
        audit = AsyncMock()
        ctx = _AuditContext(request=request_obj, audit_service=audit)
        await ctx._emit("requested")
        audit.emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_emit_guard_uses_audit_service(self, request_obj: AIRequest) -> None:
        """_emit_guard delegates to audit_service.emit."""
        audit = AsyncMock()
        ctx = _AuditContext(request=request_obj, audit_service=audit)
        gr = GuardResult(guard_name="g1", verdict="safe", categories=[])
        await ctx._emit_guard("guarded.input", gr)
        audit.emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_emit_final_completed(self, request_obj: AIRequest) -> None:
        """_emit_final with a successful response emits COMPLETED."""
        audit = AsyncMock()
        resp = AIResponse(
            content="hi",
            tokens_prompt=5,
            tokens_completion=3,
            cost_usd=0.0001,
            model_used="gpt-4",
        )
        ctx = _AuditContext(
            request=request_obj,
            audit_service=audit,
            final_response=resp,
            model_used="gpt-4",
        )
        start = 0
        await ctx._emit_final(start)
        audit.emit.assert_awaited_once()
        event = audit.emit.await_args[0][0]
        assert event.event_type.name == "COMPLETED"
        assert event.tokens_total == 8
        assert event.cost_usd == 0.0001

    @pytest.mark.asyncio
    async def test_emit_final_blocked(self, request_obj: AIRequest) -> None:
        """_emit_final with blocked output emits DENIED."""
        audit = AsyncMock()
        resp = AIResponse(content="blocked", guardrails_verdict={"output": "blocked"})
        ctx = _AuditContext(
            request=request_obj, audit_service=audit, final_response=resp
        )
        await ctx._emit_final(0)
        event = audit.emit.await_args[0][0]
        assert event.event_type.name == "DENIED"
        assert event.error_class == "GuardrailBlocked"

    @pytest.mark.asyncio
    async def test_emit_final_failed_no_response(self, request_obj: AIRequest) -> None:
        """_emit_final without response emits FAILED."""
        audit = AsyncMock()
        ctx = _AuditContext(request=request_obj, audit_service=audit)
        await ctx._emit_final(0)
        event = audit.emit.await_args[0][0]
        assert event.event_type.name == "FAILED"
        assert event.error_class == "InternalError"

    @pytest.mark.asyncio
    async def test_emit_no_audit_service_no_raise(self, request_obj: AIRequest) -> None:
        """_emit without audit_service should not raise (fallback path)."""
        ctx = _AuditContext(request=request_obj, audit_service=None)
        await ctx._emit("requested")


class TestEmitWrapper:
    """Tests for :func:`_emit_wrapper`."""

    @pytest.mark.asyncio
    async def test_with_audit_service(self) -> None:
        """Delegates to audit_service.emit when provided."""
        audit = AsyncMock()
        event = MagicMock()
        await _emit_wrapper(event, audit)
        audit.emit.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_with_none_no_raise(self) -> None:
        """Without audit_service it falls back and should not raise."""
        event = MagicMock()
        await _emit_wrapper(event, None)
