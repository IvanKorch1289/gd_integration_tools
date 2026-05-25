"""Unit-тесты hybrid-адаптера :mod:`services.ai.gateway_adapter` (S25 W3, ADR-NEW-19).

Проверяют:

* при ``feature_flags.ai_gateway_enforce=False`` (default) вызывается
  ``legacy_callable``;
* при ``feature_flags.ai_gateway_enforce=True`` вызывается
  :meth:`AIGateway.invoke` и возвращается ``response.content``;
* :class:`AIGatewayAdapter` корректно проксирует вызов с inj. gateway.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.ai import AIGateway, AIRequest, AIResponse
from src.backend.services.ai.gateway_adapter import AIGatewayAdapter, invoke_via_gateway


@pytest.mark.asyncio
async def test_adapter_calls_legacy_when_flag_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При flag=OFF (default) вызывается legacy_callable с переданными аргументами."""
    from src.backend.core.config import features as features_module

    monkeypatch.setattr(features_module.feature_flags, "ai_gateway_enforce", False)

    legacy_mock = AsyncMock(return_value="legacy-result")
    result = await invoke_via_gateway(
        workflow_id="credit_check",
        tenant_id="t-1",
        correlation_id="req-abc",
        prompt="Hello AI",
        legacy_callable=legacy_mock,
        legacy_args=("arg1",),
        legacy_kwargs={"kw": "value"},
    )
    legacy_mock.assert_awaited_once_with("arg1", kw="value")
    assert result == "legacy-result"


@pytest.mark.asyncio
async def test_adapter_calls_gateway_when_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При flag=ON вызывается AIGateway.invoke() с AIRequest из параметров."""
    from src.backend.core.config import features as features_module

    monkeypatch.setattr(features_module.feature_flags, "ai_gateway_enforce", True)

    gateway = AIGateway()
    invoke_mock = AsyncMock(return_value=AIResponse(content="ai-gateway-result"))
    monkeypatch.setattr(gateway, "invoke", invoke_mock)

    legacy_mock = AsyncMock(return_value="should-not-be-called")

    result = await invoke_via_gateway(
        workflow_id="credit_check",
        tenant_id="t-1",
        correlation_id="req-abc",
        prompt="Hello AI",
        legacy_callable=legacy_mock,
        gateway=gateway,
    )
    legacy_mock.assert_not_awaited()
    invoke_mock.assert_awaited_once()
    call_request: AIRequest = invoke_mock.await_args.args[0]
    assert call_request.workflow_id == "credit_check"
    assert call_request.tenant_id == "t-1"
    assert call_request.correlation_id == "req-abc"
    assert call_request.prompt_inline == "Hello AI"
    assert call_request.stream is False
    assert result == "ai-gateway-result"


@pytest.mark.asyncio
async def test_adapter_stream_flag_propagated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``stream=True`` пробрасывается в AIRequest."""
    from src.backend.core.config import features as features_module

    monkeypatch.setattr(features_module.feature_flags, "ai_gateway_enforce", True)

    gateway = AIGateway()
    invoke_mock = AsyncMock(return_value=AIResponse(content="streamed"))
    monkeypatch.setattr(gateway, "invoke", invoke_mock)

    await invoke_via_gateway(
        workflow_id="doc_summarize",
        tenant_id="t-2",
        correlation_id="req-xyz",
        prompt="Long document",
        legacy_callable=AsyncMock(),
        gateway=gateway,
        stream=True,
    )
    call_request: AIRequest = invoke_mock.await_args.args[0]
    assert call_request.stream is True


@pytest.mark.asyncio
async def test_adapter_default_gateway_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без передачи ``gateway`` создаётся default AIGateway()."""
    from src.backend.core.config import features as features_module

    monkeypatch.setattr(features_module.feature_flags, "ai_gateway_enforce", True)

    constructed: list[Any] = []

    def _capture(*args: Any, **kwargs: Any) -> AIGateway:
        instance = AIGateway()
        constructed.append(instance)
        return instance

    monkeypatch.setattr(
        "src.backend.services.ai.gateway_adapter.AIGateway", _capture
    )
    response = AIResponse(content="default-gw")

    # Подменяем invoke для всех новых instance'ов
    original_init = AIGateway.__init__

    def _patched_init(self: AIGateway, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        self.invoke = AsyncMock(return_value=response)  # type: ignore[method-assign]

    monkeypatch.setattr(AIGateway, "__init__", _patched_init)

    result = await invoke_via_gateway(
        workflow_id="doc_summarize",
        tenant_id="t-1",
        correlation_id="req-1",
        prompt="p",
        legacy_callable=AsyncMock(),
    )
    assert result == "default-gw"
    assert len(constructed) == 1


@pytest.mark.asyncio
async def test_class_adapter_proxies_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """AIGatewayAdapter.call() делегирует в invoke_via_gateway с inj. gateway."""
    from src.backend.core.config import features as features_module

    monkeypatch.setattr(features_module.feature_flags, "ai_gateway_enforce", True)

    gateway = AIGateway()
    invoke_mock = AsyncMock(return_value=AIResponse(content="adapter-content"))
    monkeypatch.setattr(gateway, "invoke", invoke_mock)
    adapter = AIGatewayAdapter(gateway=gateway)

    result = await adapter.call(
        workflow_id="credit_check",
        tenant_id="t-1",
        correlation_id="req-abc",
        prompt="prompt",
        legacy_callable=AsyncMock(),
    )
    assert result == "adapter-content"
    invoke_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_class_adapter_legacy_path_when_flag_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AIGatewayAdapter при flag=OFF не использует inj. gateway, идёт в legacy."""
    from src.backend.core.config import features as features_module

    monkeypatch.setattr(features_module.feature_flags, "ai_gateway_enforce", False)

    gateway = AIGateway()
    invoke_mock = AsyncMock()
    monkeypatch.setattr(gateway, "invoke", invoke_mock)
    adapter = AIGatewayAdapter(gateway=gateway)

    legacy_mock = AsyncMock(return_value={"legacy": True})
    result = await adapter.call(
        workflow_id="credit_check",
        tenant_id="t-1",
        correlation_id="req-abc",
        prompt="prompt",
        legacy_callable=legacy_mock,
    )
    assert result == {"legacy": True}
    legacy_mock.assert_awaited_once()
    invoke_mock.assert_not_awaited()
