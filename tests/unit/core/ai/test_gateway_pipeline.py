"""Тесты production-pipeline :class:`AIGateway` (Sprint 25 W1 cut).

Покрывают:

* шаг 1 (PolicyResolver) — strict + non-strict режимы;
* шаг 2 (CapabilityGate) — sync и async ``check``;
* шаг 3 + 8 (Presidio sanitizers) — input/output;
* шаг 4 + 7 (guards) — no-op при отсутствии policy_enforcer;
* шаг 6 (ModelRouter / LiteLLM) — full path с моками;
* шаг 9a (audit) — AuditService.emit вызывается с правильными полями;
* шаг 9b (cost-track) — record_cost / record_tokens при наличии trackera.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.ai import AIGateway, AIRequest, AIResponse


class _FakeSanitizerResult:
    """Имитирует :class:`SanitizationResult` для тестов."""

    def __init__(self, sanitized_text: str, replacements: dict[str, str]) -> None:
        self.sanitized_text = sanitized_text
        self.replacements = replacements


class _FakeSanitizer:
    """Простейший sanitizer: маскирует e-mail на ``[EMAIL_1]``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def sanitize_async(
        self, text: str, *, language: str | None = None
    ) -> _FakeSanitizerResult:
        self.calls.append((text, language))
        if "@" in text:
            return _FakeSanitizerResult(
                sanitized_text=text.replace("alice@x.io", "[EMAIL_1]"),
                replacements={"[EMAIL_1]": "alice@x.io"},
            )
        return _FakeSanitizerResult(sanitized_text=text, replacements={})


class _FakeLiteLLMGateway:
    """LiteLLMGateway-like mock с предсказуемым ответом."""

    def __init__(
        self,
        *,
        content: str = "ok",
        model: str = "openai/gpt-4o-mini",
        prompt_tokens: int = 5,
        completion_tokens: int = 7,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._payload = {
            "model": model,
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            },
        }

    async def acompletion(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append(
            {"messages": messages, "model": model, "stream": stream, **kwargs}
        )
        return dict(self._payload)


@pytest.fixture()
def enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Включает ``ai_gateway_enforce`` для теста."""
    from src.backend.core.config import features as features_module

    monkeypatch.setattr(features_module.feature_flags, "ai_gateway_enforce", True)
    monkeypatch.setattr(features_module.feature_flags, "ai_policy_enforce", False)


@pytest.fixture()
def basic_request() -> AIRequest:
    return AIRequest(
        workflow_id="credit_check",
        tenant_id="t-1",
        correlation_id="req-abc",
        prompt_inline="Контакт: alice@x.io",
    )


@pytest.mark.asyncio
async def test_pipeline_runs_end_to_end_with_mocked_deps(
    enforced: None, basic_request: AIRequest
) -> None:
    """Полный pipeline проходит все 9 шагов с моками зависимостей."""
    sanitizer = _FakeSanitizer()
    llm = _FakeLiteLLMGateway(content="Привет! [EMAIL_1]")
    audit = MagicMock()
    audit.emit = AsyncMock()
    cost_tracker = MagicMock()
    cost_tracker.record_cost = MagicMock()
    cost_tracker.record_tokens = MagicMock()

    gateway = AIGateway(
        sanitizer=sanitizer,
        llm_gateway=llm,
        audit_service=audit,
        cost_tracker=cost_tracker,
    )

    response = await gateway.invoke(basic_request)

    assert isinstance(response, AIResponse)
    # sanitizer вызван дважды (input + output); во втором вызове виден [EMAIL_1]
    # от LLM-ответа, в первом — оригинальный prompt до маски.
    assert len(sanitizer.calls) == 2
    assert any("[EMAIL_1]" in call[0] for call in sanitizer.calls)
    # LiteLLMGateway получил sanitized prompt
    assert len(llm.calls) == 1
    assert llm.calls[0]["messages"][0]["content"] == "Контакт: [EMAIL_1]"
    # audit.emit вызван
    audit.emit.assert_awaited_once()
    audit_kwargs = audit.emit.await_args.kwargs
    assert audit_kwargs["event"] == "ai.invocation.completed"
    assert audit_kwargs["correlation_id"] == "req-abc"
    assert audit_kwargs["tenant_id"] == "t-1"
    # cost-tracker вызван
    cost_tracker.record_tokens.assert_called_once()
    # tokens из usage блока
    assert response.tokens_prompt == 5
    assert response.tokens_completion == 7
    assert response.model_used == "openai/gpt-4o-mini"
    # PII detected = True (input маска прошла)
    assert response.pii_detected is True


@pytest.mark.asyncio
async def test_pipeline_passes_fallbacks_from_policy(
    enforced: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Policy.model_router.fallback передаётся в LiteLLMGateway."""
    from src.backend.core.ai.policy.spec import AIPolicySpec, ModelRouterSpec

    policy = AIPolicySpec(
        name="credit_check",
        workflow_pattern="credit_check*",
        tenant_pattern="*",
        model_router=ModelRouterSpec(
            primary="openai/gpt-4o-mini",
            fallback=["anthropic/claude-sonnet-4-6"],
        ),
        required=False,
    )

    class _Resolver:
        async def resolve(self, *, workflow_id: str, tenant_id: str) -> AIPolicySpec:
            assert workflow_id == "credit_check"
            return policy

    llm = _FakeLiteLLMGateway()
    gateway = AIGateway(
        policy_resolver=_Resolver(),
        sanitizer=None,  # без sanitizer'a — чтобы исключить Presidio fallback
        llm_gateway=llm,
    )

    response = await gateway.invoke(
        AIRequest(
            workflow_id="credit_check",
            tenant_id="t-1",
            correlation_id="req-1",
            prompt_inline="Hi",
        )
    )
    assert isinstance(response, AIResponse)
    assert llm.calls[0]["model"] == "openai/gpt-4o-mini"
    assert llm.calls[0]["fallbacks"] == ["anthropic/claude-sonnet-4-6"]


@pytest.mark.asyncio
async def test_pipeline_strict_policy_raises_when_missing(
    enforced: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """При ``ai_policy_enforce=True`` и ``None``-policy поднимается ошибка."""
    from src.backend.core.ai.policy.resolver import PolicyNotResolvedError
    from src.backend.core.config import features as features_module

    monkeypatch.setattr(features_module.feature_flags, "ai_policy_enforce", True)

    class _Resolver:
        async def resolve(self, **kwargs: Any) -> None:
            return None

    gateway = AIGateway(policy_resolver=_Resolver())
    with pytest.raises(PolicyNotResolvedError):
        await gateway.invoke(
            AIRequest(
                workflow_id="unknown",
                tenant_id="t-1",
                correlation_id="req-1",
            )
        )


@pytest.mark.asyncio
async def test_capability_gate_called_with_workflow_id(
    enforced: None, basic_request: AIRequest
) -> None:
    """CapabilityGate.check получает строку ``ai.invoke.<workflow_id>``."""
    gate = MagicMock()
    gate.check = MagicMock(return_value=None)
    llm = _FakeLiteLLMGateway()

    gateway = AIGateway(capability_gate=gate, sanitizer=None, llm_gateway=llm)
    await gateway.invoke(basic_request)
    gate.check.assert_called_once_with("ai.invoke.credit_check")


@pytest.mark.asyncio
async def test_input_guards_skipped_when_no_enforcer(
    enforced: None, basic_request: AIRequest
) -> None:
    """guards шаг 4 — no-op если policy_enforcer не задан."""
    llm = _FakeLiteLLMGateway()
    gateway = AIGateway(sanitizer=None, llm_gateway=llm)
    response = await gateway.invoke(basic_request)
    assert isinstance(response, AIResponse)


@pytest.mark.asyncio
async def test_pii_not_detected_when_sanitizer_returns_clean(
    enforced: None,
) -> None:
    """Без PII в ответе ``pii_detected = False``."""
    sanitizer = _FakeSanitizer()
    llm = _FakeLiteLLMGateway(content="Простой ответ")
    gateway = AIGateway(sanitizer=sanitizer, llm_gateway=llm)

    response = await gateway.invoke(
        AIRequest(
            workflow_id="wf",
            tenant_id="t-1",
            correlation_id="req-1",
            prompt_inline="Простой prompt",
        )
    )
    assert response.pii_detected is False
    assert response.content == "Простой ответ"


@pytest.mark.asyncio
async def test_audit_failure_does_not_break_pipeline(
    enforced: None, basic_request: AIRequest
) -> None:
    """Если AuditService.emit падает — invoke всё равно возвращает response."""
    llm = _FakeLiteLLMGateway()
    audit = MagicMock()
    audit.emit = AsyncMock(side_effect=RuntimeError("CH down"))
    gateway = AIGateway(sanitizer=None, llm_gateway=llm, audit_service=audit)
    response = await gateway.invoke(basic_request)
    assert isinstance(response, AIResponse)
    audit.emit.assert_awaited_once()


@pytest.mark.asyncio
async def test_pass_through_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """При ``ai_gateway_enforce=False`` (default) — scaffold response."""
    from src.backend.core.config import features as features_module

    monkeypatch.setattr(features_module.feature_flags, "ai_gateway_enforce", False)
    gateway = AIGateway()
    response = await gateway.invoke(
        AIRequest(workflow_id="x", tenant_id="t", correlation_id="c")
    )
    assert response.model_used == "pass-through-scaffold"


@pytest.mark.asyncio
async def test_provider_from_model_helper() -> None:
    """``_provider_from_model`` корректно парсит slash-формат."""
    assert AIGateway._provider_from_model("openai/gpt-4o") == "openai"
    assert AIGateway._provider_from_model("anthropic/claude-3-7") == "anthropic"
    assert AIGateway._provider_from_model("gpt-4o-mini") == "openai"


@pytest.mark.asyncio
async def test_extract_completion_handles_dict_response() -> None:
    """``_extract_completion`` парсит dict-ответ litellm."""
    payload = {
        "model": "openai/gpt-4o-mini",
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 4},
    }
    content, p, c, m = AIGateway._extract_completion(payload, fallback_model="x")
    assert content == "hello"
    assert p == 3
    assert c == 4
    assert m == "openai/gpt-4o-mini"


@pytest.mark.asyncio
async def test_language_from_policy_extracts_from_sanitizer_name(
    enforced: None,
) -> None:
    """Язык извлекается из ``presidio:ru`` → ``ru``."""
    from src.backend.core.ai.policy.spec import (
        AIPolicySpec,
        ModelRouterSpec,
        SanitizerRef,
    )

    policy = AIPolicySpec(
        name="x",
        workflow_pattern="*",
        tenant_pattern="*",
        model_router=ModelRouterSpec(primary="openai/gpt-4o-mini"),
        input_sanitizers=[SanitizerRef(name="presidio:en")],
    )
    assert AIGateway._language_from_policy(policy, default="ru") == "en"

    policy2 = AIPolicySpec(
        name="x",
        workflow_pattern="*",
        tenant_pattern="*",
        model_router=ModelRouterSpec(primary="openai/gpt-4o-mini"),
        input_sanitizers=[SanitizerRef(name="presidio", config={"language": "uk"})],
    )
    assert AIGateway._language_from_policy(policy2, default="ru") == "uk"
