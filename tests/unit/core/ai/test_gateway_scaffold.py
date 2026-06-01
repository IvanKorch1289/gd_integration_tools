"""Smoke-тесты scaffold AIGateway (Sprint 25 W1, ADR-NEW-19).

Проверяют:

* импорт :class:`AIGateway` / :class:`AIRequest` / :class:`AIResponse`;
* pass-through при ``feature_flags.ai_gateway_enforce = False``;
* enforced-pipeline поднимает ``NotImplementedError`` на первом шаге
  (не интегрирован до Wave S25 W2).
"""

from __future__ import annotations

import pytest

from src.backend.core.ai import AIGateway, AIRequest, AIResponse


def test_ai_request_dataclass_defaults() -> None:
    """AIRequest имеет ожидаемые поля и slots."""
    req = AIRequest(
        workflow_id="credit_check",
        tenant_id="t-1",
        correlation_id="req-abc",
    )
    assert req.workflow_id == "credit_check"
    assert req.tenant_id == "t-1"
    assert req.correlation_id == "req-abc"
    assert req.prompt_ref is None
    assert req.prompt_inline is None
    assert req.context == {}
    assert req.stream is False
    with pytest.raises(AttributeError):
        req.workflow_id = "other"  # type: ignore[misc]


def test_ai_response_dataclass_defaults() -> None:
    """AIResponse имеет ожидаемые поля и slots."""
    resp = AIResponse(content="hello")
    assert resp.content == "hello"
    assert resp.structured is None
    assert resp.tokens_prompt == 0
    assert resp.tokens_completion == 0
    assert resp.cost_usd == 0.0
    assert resp.model_used == ""
    assert resp.pii_detected is False
    assert resp.guardrails_verdict == {}


@pytest.mark.asyncio
async def test_invoke_pass_through_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """При ``ai_gateway_enforce=False`` invoke возвращает scaffold-AIResponse."""
    from src.backend.core.config import features as features_module

    monkeypatch.setattr(features_module.feature_flags, "ai_gateway_enforce", False)

    gateway = AIGateway()
    response = await gateway.invoke(
        AIRequest(
            workflow_id="credit_check",
            tenant_id="t-1",
            correlation_id="req-abc",
        )
    )
    assert isinstance(response, AIResponse)
    assert response.model_used == "pass-through-scaffold"
    assert response.content == ""


@pytest.mark.asyncio
async def test_invoke_enforced_runs_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """При ``ai_gateway_enforce=True`` запускается 9-step pipeline.

    Без resolved policy и без работающего LiteLLM шаг 6 поднимает
    ``GatewayUnavailable`` (default-OFF litellm) — это ожидаемо, проверяем
    что pipeline проходит до шага invoke_llm, а не падает раньше.
    """
    from src.backend.core.config import features as features_module
    from src.backend.services.ai.gateway.exceptions import GatewayUnavailable

    monkeypatch.setattr(features_module.feature_flags, "ai_gateway_enforce", True)
    monkeypatch.setattr(features_module.feature_flags, "ai_policy_enforce", False)

    gateway = AIGateway()
    with pytest.raises(GatewayUnavailable):
        await gateway.invoke(
            AIRequest(
                workflow_id="credit_check",
                tenant_id="t-1",
                correlation_id="req-abc",
                prompt_inline="Hello AI",
            )
        )


def test_gateway_construction_optional_deps() -> None:
    """AIGateway конструируется без зависимостей (все Optional)."""
    gateway = AIGateway()
    assert gateway is not None
    gateway_with_deps = AIGateway(
        policy_resolver=object(),
        capability_gate=object(),
        audit_service=object(),
        cost_tracker=object(),
    )
    assert gateway_with_deps is not None
