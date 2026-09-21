"""S177 M2: AIGateway production fail-closed wiring guard (regression tests).

Покрывает ``AIGateway._enforce_production_wiring`` — guard обязательных
DI-зависимостей (policy_resolver, capability_gate, token_budget) на
``app.environment == "production"``.

Сценарии:
1. На production без DI-инъекций → AIGatewayProductionWiringError
   (наследник AIGatewayEnforcementRequiredError, чтобы endpointы,
   обрабатывающие 503, не сломались).
2. На production с полным DI → invoke доходит до _enforced_invoke
   (mock invoke через policy_resolver с PolicyNone — но pipeline пройдёт
   guard).
3. На development/staging без DI → guard не активен, как раньше.
4. Вне production флаг tenant_token_budget_enabled не меняет поведение.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


def _patch_app_environment(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """Подменяет ``settings.app.environment`` на ``value``."""
    from src.backend.core.config import settings as settings_module

    monkeypatch.setattr(settings_module.settings.app, "environment", value)


@pytest.mark.asyncio
async def test_production_no_di_raises_production_wiring_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production + AIGateway() без DI → AIGatewayProductionWiringError."""
    from src.backend.core.ai.errors import AIGatewayProductionWiringError
    from src.backend.core.ai.gateway import AIGateway
    from src.backend.core.ai.gateway_models import AIRequest

    _patch_app_environment(monkeypatch, "production")

    gateway = AIGateway()
    request = AIRequest(
        workflow_id="test.workflow",
        tenant_id="t-1",
        correlation_id="req-prod-001",
        prompt_inline="ping",
    )

    with pytest.raises(AIGatewayProductionWiringError) as exc_info:
        await gateway.invoke(request)
    msg = str(exc_info.value)
    for missing in ("policy_resolver", "capability_gate", "token_budget"):
        assert missing in msg, f"Expected {missing!r} in error message, got: {msg!r}"


@pytest.mark.asyncio
async def test_production_wiring_error_is_enforcement_error() -> None:
    """AIGatewayProductionWiringError — subclass AIGatewayEnforcementRequiredError.

    Endpoint-обработчики, которые ловят AIGatewayEnforcementRequiredError
    для маппинга в 503, должны также ловить новый класс.

    Round 40 fix: ``AIGatewayProductionWiringError`` теперь subclass
    ``AIGatewayEnforcementRequiredError`` (был bare ``RuntimeError``).
    """
    from src.backend.core.ai.errors import (
        AIGatewayEnforcementRequiredError,
        AIGatewayProductionWiringError,
    )

    assert issubclass(AIGatewayProductionWiringError, AIGatewayEnforcementRequiredError)


@pytest.mark.asyncio
async def test_production_partial_di_raises_with_missing_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production + только policy_resolver → raise с перечислением остальных."""
    from src.backend.core.ai.errors import AIGatewayProductionWiringError
    from src.backend.core.ai.gateway import AIGateway
    from src.backend.core.ai.gateway_models import AIRequest

    _patch_app_environment(monkeypatch, "production")

    gateway = AIGateway(policy_resolver=MagicMock())
    request = AIRequest(
        workflow_id="wf", tenant_id="t-1", correlation_id="req", prompt_inline="p"
    )

    with pytest.raises(AIGatewayProductionWiringError) as exc_info:
        await gateway.invoke(request)
    msg = str(exc_info.value)
    # Раздел "missing DI" — после двоеточия и до первой точки.
    # (В тексте подсказки 'Wire them through AIGateway(policy_resolver=...)'
    # встречается имя — поэтому проверяем именно первую секцию.)
    missing_section = msg.split("Wire them through")[0]
    assert "capability_gate" in missing_section
    assert "token_budget" in missing_section
    assert "policy_resolver" not in missing_section


@pytest.mark.asyncio
async def test_production_full_di_reaches_enforced_invoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production + полный DI → guard проходит, доходит до _enforced_invoke.

    Подменяем ``_enforced_invoke`` на AsyncMock чтобы изолировать от LLM.
    """
    from src.backend.core.ai.gateway import AIGateway
    from src.backend.core.ai.gateway_models import AIRequest, AIResponse

    _patch_app_environment(monkeypatch, "production")

    gateway = AIGateway(
        policy_resolver=MagicMock(),
        capability_gate=MagicMock(),
        token_budget=MagicMock(),
    )
    sentinel = AIResponse(content="ok")
    enforced_mock = AsyncMock(return_value=sentinel)
    monkeypatch.setattr(gateway, "_enforced_invoke", enforced_mock)

    request = AIRequest(
        workflow_id="wf", tenant_id="t-1", correlation_id="req", prompt_inline="p"
    )
    response = await gateway.invoke(request)
    enforced_mock.assert_awaited_once_with(request)
    assert response is sentinel


@pytest.mark.asyncio
async def test_development_no_di_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Development + AIGateway() без DI → guard пропускает (backward-compat)."""
    from src.backend.core.ai.gateway import AIGateway
    from src.backend.core.ai.gateway_models import AIRequest, AIResponse

    _patch_app_environment(monkeypatch, "development")

    gateway = AIGateway()
    sentinel = AIResponse(content="dev-ok")
    enforced_mock = AsyncMock(return_value=sentinel)
    monkeypatch.setattr(gateway, "_enforced_invoke", enforced_mock)

    request = AIRequest(
        workflow_id="wf", tenant_id="t-1", correlation_id="req", prompt_inline="p"
    )
    response = await gateway.invoke(request)
    assert response is sentinel


@pytest.mark.asyncio
async def test_staging_no_di_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """Staging + AIGateway() без DI → guard пропускает."""
    from src.backend.core.ai.gateway import AIGateway
    from src.backend.core.ai.gateway_models import AIRequest, AIResponse

    _patch_app_environment(monkeypatch, "staging")

    gateway = AIGateway()
    sentinel = AIResponse(content="staging-ok")
    enforced_mock = AsyncMock(return_value=sentinel)
    monkeypatch.setattr(gateway, "_enforced_invoke", enforced_mock)

    request = AIRequest(
        workflow_id="wf", tenant_id="t-1", correlation_id="req", prompt_inline="p"
    )
    response = await gateway.invoke(request)
    assert response is sentinel


def test_production_wiring_error_str_lists_all_missing() -> None:
    """Текст ошибки содержит все три обязательных имени.

    Round 41 fix: тест использует canonical API ``missing=tuple[str, ...]``
    (вместо ошибочного single-string как в original forward-looking design).
    ``__str__`` форматирует ``missing ['policy_resolver', ...]``.
    """
    from src.backend.core.ai.errors import AIGatewayProductionWiringError

    err = AIGatewayProductionWiringError(
        missing=("policy_resolver", "capability_gate", "token_budget")
    )
    msg = str(err)
    assert "policy_resolver" in msg
    assert "capability_gate" in msg
    assert "token_budget" in msg


def test_enforce_production_wiring_returns_none_when_development() -> None:
    """_enforce_production_wiring — explicit sync smoke test."""
    from src.backend.core.ai.gateway import AIGateway

    gateway = AIGateway()
    # development: возврат None, без raise.
    assert gateway._enforce_production_wiring() is None


def test_enforce_production_wiring_is_idempotent() -> None:
    """Повторный вызов _enforce_production_wiring — идемпотентен.

    Guard не имеет side-effects, не модифицирует state.
    """
    from src.backend.core.ai.gateway import AIGateway

    gateway = AIGateway(policy_resolver=MagicMock(), capability_gate=MagicMock())
    assert gateway._enforce_production_wiring() is None
    assert gateway._enforce_production_wiring() is None


def test_aigateway_stores_token_budget_attribute() -> None:
    """AIGateway хранит _token_budget (регрессия S177 M2 guard).

    Guard полагается на ``self._token_budget``; если кто-то выпилит
    атрибут в __init__, production-wiring fail-closed сломается
    (AttributeError вместо AIGatewayProductionWiringError).
    """
    from src.backend.core.ai.gateway import AIGateway

    budget = MagicMock(name="TokenBudget")
    gateway = AIGateway(token_budget=budget)
    # ``_token_budget`` — instance-attr, проставляется в __init__ facade.
    # Слот не обязателен; mixin family допускает запись (см. S141 W2).
    assert getattr(gateway, "_token_budget", None) is budget
    # Подтверждаем, что тот же атрибут доступен и через mixin protocol —
    # EnforcedInvokeMixin._enforce_token_budget_pre_call полагается
    # именно на ``self._token_budget``.
    from src.backend.core.ai.gateway_orchestrator_mixin import EnforcedInvokeMixin

    assert hasattr(EnforcedInvokeMixin, "_enforce_token_budget_pre_call")
