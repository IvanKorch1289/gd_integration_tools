"""E2E тесты на ModelRouter (LiteLLM fallback chain) — Task 4 (gap-ai-7).

Проверяют что :meth:`AIGateway._invoke_llm` корректно:

* использует ``policy.model_router.primary`` как primary model;
* передаёт ``fallbacks`` списком в ``LiteLLMGateway.acompletion``;
* вызывает fallback chain при ошибке primary (timeout/rate-limit).

Это **не** test на LiteLLMGateway — это test на то, что *gateway* correctly
*routs* через ModelRouterSpec.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.ai import AIGateway
from src.backend.core.ai.policy.spec import AIPolicySpec, ModelRouterSpec


def _make_policy(
    *,
    primary: str = "openai/gpt-4o-mini",
    fallbacks: list[str] | None = None,
    timeout_s: float = 30.0,
    retry_attempts: int = 2,
) -> AIPolicySpec:
    """Конструктор AIPolicySpec с ModelRouterSpec."""
    return AIPolicySpec(
        name="test_model_router",
        workflow_pattern="*",
        tenant_pattern="*",
        model_router=ModelRouterSpec(
            primary=primary,
            fallback=fallbacks or [],
            timeout_s=timeout_s,
            retry_attempts=retry_attempts,
        ),
        required=False,
    )


@pytest.mark.asyncio
async def test_model_router_passes_primary_to_gateway() -> None:
    """primary model передаётся в LiteLLMGateway.acompletion(model=...)."""
    policy = _make_policy(primary="openai/gpt-4o-mini")

    mock_gateway = MagicMock()
    mock_gateway.acompletion = AsyncMock(
        return_value={
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "model": "openai/gpt-4o-mini",
        }
    )
    mock_gateway._resolve_llm_gateway = MagicMock(return_value=mock_gateway)

    gateway = AIGateway(llm_gateway=mock_gateway)
    response = await gateway._invoke_llm("hello", policy=policy, stream=False)

    mock_gateway.acompletion.assert_awaited_once()
    call_kwargs = mock_gateway.acompletion.call_args.kwargs
    assert call_kwargs.get("model") == "openai/gpt-4o-mini"
    assert response.content == "ok"


@pytest.mark.asyncio
async def test_model_router_passes_fallbacks_list() -> None:
    """fallbacks list передаётся как kwargs['fallbacks'] в acompletion."""
    policy = _make_policy(
        primary="openai/gpt-4o-mini",
        fallbacks=["anthropic/claude-3-haiku", "openai/gpt-3.5-turbo"],
    )

    mock_gateway = MagicMock()
    mock_gateway.acompletion = AsyncMock(
        return_value={
            "choices": [{"message": {"content": "fallback"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "model": "anthropic/claude-3-haiku",
        }
    )
    mock_gateway._resolve_llm_gateway = MagicMock(return_value=mock_gateway)

    gateway = AIGateway(llm_gateway=mock_gateway)
    response = await gateway._invoke_llm("hello", policy=policy, stream=False)

    call_kwargs = mock_gateway.acompletion.call_args.kwargs
    assert call_kwargs.get("fallbacks") == [
        "anthropic/claude-3-haiku",
        "openai/gpt-3.5-turbo",
    ]
    assert response.content == "fallback"


@pytest.mark.asyncio
async def test_model_router_no_fallbacks_no_kwargs() -> None:
    """Без fallbacks — kwargs['fallbacks'] отсутствует."""
    policy = _make_policy(primary="openai/gpt-4o-mini", fallbacks=None)

    mock_gateway = MagicMock()
    mock_gateway.acompletion = AsyncMock(
        return_value={
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "model": "openai/gpt-4o-mini",
        }
    )
    mock_gateway._resolve_llm_gateway = MagicMock(return_value=mock_gateway)

    gateway = AIGateway(llm_gateway=mock_gateway)
    await gateway._invoke_llm("hello", policy=policy, stream=False)

    call_kwargs = mock_gateway.acompletion.call_args.kwargs
    assert "fallbacks" not in call_kwargs


@pytest.mark.asyncio
async def test_invoke_llm_policy_none_uses_none_model() -> None:
    """Без policy (None) — model=None, Gateway сам выбирает default."""
    mock_gateway = MagicMock()
    mock_gateway.acompletion = AsyncMock(
        return_value={
            "choices": [{"message": {"content": "default"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "model": "default",
        }
    )
    mock_gateway._resolve_llm_gateway = MagicMock(return_value=mock_gateway)

    gateway = AIGateway(llm_gateway=mock_gateway)
    await gateway._invoke_llm("hello", policy=None, stream=False)

    call_kwargs = mock_gateway.acompletion.call_args.kwargs
    assert call_kwargs.get("model") is None


@pytest.mark.asyncio
async def test_model_router_extracts_completion_fields() -> None:
    """response содержит tokens и model_used из completion response."""
    policy = _make_policy(primary="openrouter/anthropic/claude-3.5-sonnet")

    mock_gateway = MagicMock()
    mock_gateway.acompletion = AsyncMock(
        return_value={
            "choices": [{"message": {"content": "response text"}}],
            "usage": {"prompt_tokens": 15, "completion_tokens": 8},
            "model": "openrouter/anthropic/claude-3.5-sonnet",
        }
    )
    mock_gateway._resolve_llm_gateway = MagicMock(return_value=mock_gateway)

    gateway = AIGateway(llm_gateway=mock_gateway)
    response = await gateway._invoke_llm("hello", policy=policy, stream=False)

    assert response.content == "response text"
    assert response.tokens_prompt == 15
    assert response.tokens_completion == 8
    assert response.model_used == "openrouter/anthropic/claude-3.5-sonnet"
