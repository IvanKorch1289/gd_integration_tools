"""Unit test для Block 1.5 (gap-ai-1.5, ADR-0072).

Проверяет AuthorizationGateway policy gate в :meth:`AIAgentService.chat`:

1. ``ai_agent_settings.policy_gate_enabled=False`` → passthrough (gate skipped).
2. gate=True + gateway allow → chat продолжается (RAG → sanitize → LLM).
3. gate=True + gateway deny → возвращает deny-envelope без LLM-вызова.
4. gate=True + gateway недоступен (None) → fail-closed deny.
5. gate=True + gateway.authorize() raises → fail-closed deny.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


@dataclass(frozen=True, slots=True)
class _Reason:
    source: str
    outcome: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class _Decision:
    allowed: bool
    correlation_id: str
    reasons: tuple[_Reason, ...]
    principal: str = "tenant-1"
    resource: str = "ai:llm"
    action: str = "call"


def _build_gateway(*, allowed: bool, raise_exc: Exception | None = None) -> Any:
    """Helper: создаёт mock AuthorizationGateway с заданным поведением."""
    gateway = MagicMock()
    if raise_exc is not None:
        gateway.authorize = AsyncMock(side_effect=raise_exc)
    else:
        decision = _Decision(
            allowed=allowed,
            correlation_id="test-cid-1",
            reasons=(_Reason(source="test", outcome="allow" if allowed else "deny"),),
        )
        gateway.authorize = AsyncMock(return_value=decision)
    return gateway


@pytest.mark.asyncio
async def test_chat_passthrough_when_gate_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При policy_gate_enabled=False _policy_gate возвращает None (continue)."""
    from src.backend.core.config import ai_2026
    from src.backend.services.ai.ai_agent import AIAgentService

    monkeypatch.setattr(
        ai_2026.ai_agent_settings, "policy_gate_enabled", False, raising=True
    )
    agent = AIAgentService()
    result = await agent._policy_gate(
        model="gpt", tenant_id="t1", route_id="r1", metadata=None
    )
    assert result is None


@pytest.mark.asyncio
async def test_chat_allows_when_gateway_returns_allow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gate=True + gateway.allow → _policy_gate возвращает None (continue)."""
    from src.backend.core.config import ai_2026
    from src.backend.services.ai.ai_agent import AIAgentService

    monkeypatch.setattr(
        ai_2026.ai_agent_settings, "policy_gate_enabled", True, raising=True
    )
    gateway = _build_gateway(allowed=True)
    monkeypatch.setattr(
        AIAgentService, "_resolve_authz_gateway", staticmethod(lambda: gateway)
    )
    agent = AIAgentService()
    result = await agent._policy_gate(
        model="gpt", tenant_id="tenant-1", route_id="r1", metadata=None
    )
    assert result is None
    gateway.authorize.assert_awaited_once()


@pytest.mark.asyncio
async def test_chat_denies_when_gateway_returns_deny(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gate=True + gateway.deny → возвращает deny-envelope с correlation_id."""
    from src.backend.core.config import ai_2026
    from src.backend.services.ai.ai_agent import AIAgentService

    monkeypatch.setattr(
        ai_2026.ai_agent_settings, "policy_gate_enabled", True, raising=True
    )
    gateway = _build_gateway(allowed=False)
    monkeypatch.setattr(
        AIAgentService, "_resolve_authz_gateway", staticmethod(lambda: gateway)
    )
    agent = AIAgentService()
    result = await agent._policy_gate(
        model="gpt", tenant_id="tenant-1", route_id="r1", metadata=None
    )
    assert result is not None
    assert result["success"] is False
    assert result["error"] == "ai.llm.policy.gate.denied"
    assert result["correlation_id"] == "test-cid-1"
    assert isinstance(result["reasons"], list)
    assert result["reasons"][0]["outcome"] == "deny"


@pytest.mark.asyncio
async def test_fail_closed_when_gateway_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gate=True + gateway is None → fail-closed deny."""
    from src.backend.core.config import ai_2026
    from src.backend.services.ai.ai_agent import AIAgentService

    monkeypatch.setattr(
        ai_2026.ai_agent_settings, "policy_gate_enabled", True, raising=True
    )
    monkeypatch.setattr(
        AIAgentService, "_resolve_authz_gateway", staticmethod(lambda: None)
    )
    agent = AIAgentService()
    result = await agent._policy_gate(
        model="gpt", tenant_id="tenant-1", route_id="r1", metadata=None
    )
    assert result is not None
    assert result["success"] is False
    assert result["error"] == "ai.llm.policy.gate.unavailable"


@pytest.mark.asyncio
async def test_fail_closed_when_gateway_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gate=True + gateway.authorize raises → fail-closed deny."""
    from src.backend.core.config import ai_2026
    from src.backend.services.ai.ai_agent import AIAgentService

    monkeypatch.setattr(
        ai_2026.ai_agent_settings, "policy_gate_enabled", True, raising=True
    )
    gateway = _build_gateway(allowed=True, raise_exc=RuntimeError("boom"))
    monkeypatch.setattr(
        AIAgentService, "_resolve_authz_gateway", staticmethod(lambda: gateway)
    )
    agent = AIAgentService()
    result = await agent._policy_gate(
        model="gpt", tenant_id="tenant-1", route_id="r1", metadata=None
    )
    assert result is not None
    assert result["success"] is False
    assert result["error"] == "ai.llm.policy.gate.error"
    assert "boom" in result["detail"]
