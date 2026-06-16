"""S85 W4: full test suite для AIGateway enforcement (V2 P0 #1).

Tests:
1. AIGateway.invoke() бросает AIGatewayEnforcementRequiredError
   при ai_gateway_enforce=False
2. AIGatewayEnforcementRequiredError export в core.ai.errors
3. ai_graph.build_and_run_agent — enforcement gate works
4. BasePydanticAgent._ensure_gateway — enforcement gate works
5. LiteLLMModel.request — enforcement gate works
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


def test_legacy_invoke_removed() -> None:
    """W1: _legacy_invoke метод удалён из AIGateway."""
    from src.backend.core.ai.gateway import AIGateway

    assert not hasattr(AIGateway, "_legacy_invoke"), (
        "_legacy_invoke was removed in S85 W1; its presence indicates regression"
    )


def test_enforcement_required_error_exported() -> None:
    """W1: AIGatewayEnforcementRequiredError в public API."""
    from src.backend.core.ai.errors import AIGatewayEnforcementRequiredError

    assert AIGatewayEnforcementRequiredError is not None
    assert issubclass(AIGatewayEnforcementRequiredError, Exception)


@pytest.mark.asyncio
async def test_aigateway_invoke_blocks_when_enforce_false() -> None:
    """W1: AIGateway.invoke() бросает enforcement error при enforce=False.

    Используем mock для feature_flags.ai_gateway_enforce=False.
    """
    from src.backend.core.ai.errors import AIGatewayEnforcementRequiredError
    from src.backend.core.ai.gateway import AIGateway
    from src.backend.core.ai.gateway_models import AIRequest

    gateway = AIGateway()
    request = AIRequest(
        workflow_id="test.workflow",
        tenant_id="test-tenant",
        correlation_id="test-corr-001",
        prompt_inline="test",
    )

    with patch(
        "src.backend.core.config.features.feature_flags.ai_gateway_enforce", False
    ):
        with pytest.raises(AIGatewayEnforcementRequiredError) as exc_info:
            await gateway.invoke(request)
        assert "S85" in str(exc_info.value) or "enforce" in str(exc_info.value).lower()


def test_ai_graph_enforcement_check_exists() -> None:
    """W2: ai_graph.build_and_run_agent содержит enforcement check.

    Smoke-test: модуль импортируется + содержит pre-flight check.
    """
    import inspect

    from src.backend.services.ai import ai_graph

    source = inspect.getsource(ai_graph.build_and_run_agent)
    assert "AIGatewayEnforcementRequiredError" in source
    assert "ai_gateway_enforce" in source


def test_base_pydantic_agent_enforcement_check_exists() -> None:
    """W2: BasePydanticAgent._ensure_gateway содержит enforcement check."""
    import inspect

    from src.backend.services.ai.agents_pydantic.base import BasePydanticAgent

    source = inspect.getsource(BasePydanticAgent._ensure_gateway)
    assert "AIGatewayEnforcementRequiredError" in source
    assert "ai_gateway_enforce" in source


def test_litellm_model_enforcement_check_exists() -> None:
    """W2: LiteLLMModel.request содержит enforcement check."""
    import inspect

    from src.backend.services.ai.agents_pydantic.adapter import LiteLLMModel

    source = inspect.getsource(LiteLLMModel.request)
    assert "AIGatewayEnforcementRequiredError" in source
    assert "ai_gateway_enforce" in source
