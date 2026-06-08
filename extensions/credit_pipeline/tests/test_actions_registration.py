# ruff: noqa: S101
"""Тесты для 3 real actions кредитного pipeline (S76 W2).

Проверяют, что каждый зарегистрированный action handler:
* вызывает соответствующий real agent (не stub);
* возвращает ``stub=False``;
* корректно прокидывает payload из kwargs.

Тесты изолированы от plugin lifecycle — handler'ы подменяются
напрямую через мок-реестр, без вызова ``on_load``/``on_shutdown``.
"""

from __future__ import annotations

from typing import Any

import pytest

from extensions.credit_pipeline.plugin import CreditPipelinePlugin
from src.backend.core.interfaces.plugin import ActionRegistryProtocol


class _RecordingRegistry:
    def __init__(self) -> None:
        self.registered: dict[str, Any] = {}

    def register(
        self, action_id: str, handler: Any, *, spec: Any | None = None
    ) -> None:
        self.registered[action_id] = handler


@pytest.fixture
async def action_handlers() -> dict[str, Any]:
    """Регистрирует plugin actions и возвращает handler'ы."""
    plugin = CreditPipelinePlugin()
    registry: ActionRegistryProtocol = _RecordingRegistry()  # type: ignore[assignment]
    await plugin.on_register_actions(registry)
    return registry.registered  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_score_action_invokes_real_scoring_agent(
    action_handlers: dict[str, Any],
) -> None:
    """``credit_pipeline.score`` → real scoring_agent, stub=False."""
    handler = action_handlers["credit_pipeline.score"]
    payload = {
        "client_id": 42,
        "amount": 200_000,
        "duration_months": 24,
        "monthly_income": 150_000,
    }
    result = await handler(payload=payload)
    assert result["agent"] == "scoring_agent"
    assert result["client_id"] == 42
    assert 0 <= result["credit_score"] <= 1000
    assert result["risk_class"] in ("LOW", "MEDIUM", "HIGH")
    assert result["stub"] is False


@pytest.mark.asyncio
async def test_parse_action_invokes_real_document_parser_agent(
    action_handlers: dict[str, Any],
) -> None:
    """``credit_pipeline.parse`` → real document_parser_agent."""
    handler = action_handlers["credit_pipeline.parse"]
    payload = {
        "applicant_id": 1,
        "amount": 100_000,
        "duration_months": 12,
        "purpose": "mortgage",
    }
    result = await handler(payload=payload)
    assert result["agent"] == "document_parser_agent"
    assert result["extracted"]["applicant_id"] == 1
    assert result["completeness_pct"] == 100
    assert result["stub"] is False


@pytest.mark.asyncio
async def test_decide_action_invokes_real_decision_agent(
    action_handlers: dict[str, Any],
) -> None:
    """``credit_pipeline.decide`` → real decision_agent."""
    handler = action_handlers["credit_pipeline.decide"]
    result = await handler(payload={"applicant_id": 1, "score": 750})
    assert result["agent"] == "decision_agent"
    assert result["approved"] is True
    assert result["credit_score"] == 750
    assert "APPROVE" in result["reason"]
    assert result["stub"] is False


@pytest.mark.asyncio
async def test_actions_chain_score_then_decide(action_handlers: dict[str, Any]) -> None:
    """Pipeline: score → decide (как в DSL call_function chain)."""
    score = await action_handlers["credit_pipeline.score"](
        payload={
            "client_id": 1,
            "amount": 100_000,
            "duration_months": 12,
            "monthly_income": 100_000,
        }
    )
    decision = await action_handlers["credit_pipeline.decide"](
        payload={"applicant_id": 1, "scoring_agent": score}
    )
    # DTI = 100k/12 / 100k = 8.3% → score 800 → APPROVE.
    assert score["credit_score"] >= 750
    assert decision["approved"] is True


@pytest.mark.asyncio
async def test_action_handles_missing_payload() -> None:
    """Action handler gracefully обрабатывает отсутствие ``payload`` (→ {})."""
    plugin = CreditPipelinePlugin()
    registry: ActionRegistryProtocol = _RecordingRegistry()  # type: ignore[assignment]
    await plugin.on_register_actions(registry)
    handler = registry.registered["credit_pipeline.score"]  # type: ignore[attr-defined]
    # Без payload — handler не должен raise.
    result = await handler()
    assert result["agent"] == "scoring_agent"
    assert result["stub"] is False
