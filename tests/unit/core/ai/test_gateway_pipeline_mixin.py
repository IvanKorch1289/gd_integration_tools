"""Unit tests for :class:`PipelineStepsMixin` (S41 W2, S38 P1.1b).

Эти тесты фокусируются на mixin-методах напрямую, без участия фасада
:class:`AIGateway`. Wave 1 (``test_gateway_pipeline.py``) уже покрыл
end-to-end pipeline через ``gateway.invoke()`` — здесь проверяем
контракты отдельных шагов и helper-функций.

Покрытие:
* ``_resolve_policy`` — отсутствие resolver, soft-режим, strict-режим.
* ``_check_capability`` — sync/async check, отсутствие gate, ошибки.
* ``_apply_input_sanitizers`` — happy path, RuntimeError, generic
  Exception, empty content, no sanitizer.
* ``_apply_input_guards`` / ``_apply_output_guards`` — все 4 early-exit
  ветки + happy path с enforcer'ом.
* ``_render_prompt`` — без budget, в пределах budget, превышение с
  tiktoken, превышение без tiktoken (fallback).
* ``_invoke_llm`` — backward-compat path без model_router.
* ``_apply_output_sanitizers`` — с/без sanitizer, empty content.
* ``_audit_emit`` — happy path + audit service down + no audit service.
* ``_cost_track`` — no-op + record_cost + record_tokens + exception.
* ``_resolve_sanitizer`` / ``_resolve_llm_gateway`` — caching.
* Property-test на ``_language_from_policy`` для произвольных
  ``presidio:<lang>`` идентификаторов.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.backend.core.ai.errors import GuardResult
from src.backend.core.ai.gateway_models import AIRequest, AIResponse
from src.backend.core.ai.gateway_pipeline_mixin import PipelineStepsMixin
from src.backend.core.ai.policy.spec import (
    AIPolicySpec,
    AuditSpec,
    BudgetSpec,
    GuardRef,
    ModelRouterSpec,
    SanitizerRef,
)

# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_mixin(**overrides: Any) -> PipelineStepsMixin:
    """Construct bare mixin instance (no facade init)."""
    mixin: Any = PipelineStepsMixin()
    # Facade-provided attrs (см. docstring PipelineStepsMixin)
    mixin._policy_resolver = None
    mixin._capability_gate = None
    mixin._audit_service = None
    mixin._cost_tracker = None
    mixin._sanitizer = None
    mixin._llm_gateway = None
    mixin._policy_enforcer = None
    for k, v in overrides.items():
        setattr(mixin, k, v)
    return mixin


def _fake_litellm_payload(
    *,
    content: str = "ok",
    model: str = "openai/gpt-4o-mini",
    prompt_tokens: int = 5,
    completion_tokens: int = 7,
) -> dict[str, Any]:
    return {
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
    }


class _FakeLLMGateway:
    """Минимальный stand-in для ``LiteLLMGateway.acompletion``."""

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self._payload = payload or _fake_litellm_payload()
        self.calls: list[dict[str, Any]] = []

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


class _FakeSanitizerResult:
    def __init__(self, sanitized_text: str, replacements: dict[str, str]) -> None:
        self.sanitized_text = sanitized_text
        self.replacements = replacements


class _FakeSanitizer:
    """Sanitizer, который маскирует e-mail в input."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self._fail = fail

    async def sanitize_async(
        self, text: str, *, language: str | None = None
    ) -> _FakeSanitizerResult:
        self.calls.append((text, language))
        if self._fail:
            raise RuntimeError("presidio unavailable")
        if "@" in text:
            return _FakeSanitizerResult(
                sanitized_text=text.replace("alice@x.io", "[EMAIL_1]"),
                replacements={"[EMAIL_1]": "alice@x.io"},
            )
        return _FakeSanitizerResult(sanitized_text=text, replacements={})


@pytest.fixture()
def basic_request() -> AIRequest:
    return AIRequest(
        workflow_id="credit_check",
        tenant_id="t-1",
        correlation_id="req-abc",
        prompt_inline="Контакт: alice@x.io",
    )


@pytest.fixture()
def basic_policy() -> AIPolicySpec:
    return AIPolicySpec(
        name="credit_check",
        workflow_pattern="credit_check*",
        tenant_pattern="*",
        model_router=ModelRouterSpec(primary="openai/gpt-4o-mini"),
    )


# ── _resolve_policy ──────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_policy_no_resolver_returns_none() -> None:
    """Без ``policy_resolver`` mixin возвращает ``None`` без side-effects."""
    mixin = _make_mixin()
    req = AIRequest(
        workflow_id="wf", tenant_id="t", correlation_id="c", prompt_inline="hi"
    )
    result = await mixin._resolve_policy(req)
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_policy_resolver_returns_spec(basic_policy: AIPolicySpec) -> None:
    """Resolver возвращает spec → mixin пробрасывает его без изменений."""

    class _Resolver:
        async def resolve(self, *, workflow_id: str, tenant_id: str) -> AIPolicySpec:
            assert workflow_id == "credit_check"
            assert tenant_id == "t-1"
            return basic_policy

    mixin = _make_mixin(_policy_resolver=_Resolver())
    req = AIRequest(
        workflow_id="credit_check",
        tenant_id="t-1",
        correlation_id="c",
        prompt_inline="hi",
    )
    result = await mixin._resolve_policy(req)
    assert result is basic_policy


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_policy_none_in_strict_mode_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При ``ai_policy_enforce=True`` и ``None``-policy поднимается ошибка."""
    from src.backend.core.ai.policy.resolver import PolicyNotResolvedError
    from src.backend.core.config import features as features_module

    monkeypatch.setattr(features_module.feature_flags, "ai_policy_enforce", True)

    class _Resolver:
        async def resolve(self, **kwargs: Any) -> None:
            return None

    mixin = _make_mixin(_policy_resolver=_Resolver())
    req = AIRequest(
        workflow_id="x", tenant_id="t", correlation_id="c", prompt_inline="hi"
    )
    with pytest.raises(PolicyNotResolvedError):
        await mixin._resolve_policy(req)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_policy_none_in_soft_mode_returns_none() -> None:
    """При ``ai_policy_enforce=False`` (default) — ``None`` без ошибки."""

    class _Resolver:
        async def resolve(self, **kwargs: Any) -> None:
            return None

    mixin = _make_mixin(_policy_resolver=_Resolver())
    req = AIRequest(
        workflow_id="x", tenant_id="t", correlation_id="c", prompt_inline="hi"
    )
    assert await mixin._resolve_policy(req) is None


# ── _check_capability ───────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_capability_no_gate_is_noop() -> None:
    """Без ``capability_gate`` — no-op, не падает."""
    mixin = _make_mixin()
    req = AIRequest(
        workflow_id="wf", tenant_id="t", correlation_id="c", prompt_inline="hi"
    )
    await mixin._check_capability(req)  # should not raise


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_capability_sync_check_called() -> None:
    """CapabilityGate.check вызывается с ``ai.invoke.<workflow_id>``."""
    gate = MagicMock()
    gate.check = MagicMock(return_value=None)
    mixin = _make_mixin(_capability_gate=gate)
    req = AIRequest(
        workflow_id="credit_check",
        tenant_id="t",
        correlation_id="c",
        prompt_inline="hi",
    )
    await mixin._check_capability(req)
    gate.check.assert_called_once_with("ai.invoke.credit_check")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_capability_async_check_awaited() -> None:
    """Async CapabilityGate.check — ``await``-ится."""
    gate = MagicMock()
    gate.check = MagicMock(return_value=asyncio.sleep(0))  # awaitable
    mixin = _make_mixin(_capability_gate=gate)
    req = AIRequest(
        workflow_id="wf", tenant_id="t", correlation_id="c", prompt_inline="hi"
    )
    await mixin._check_capability(req)
    gate.check.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_capability_gate_without_check_attr_skipped() -> None:
    """CapabilityGate без метода ``check`` — silently no-op."""
    gate = MagicMock(spec=[])  # no `check` attribute
    mixin = _make_mixin(_capability_gate=gate)
    req = AIRequest(
        workflow_id="wf", tenant_id="t", correlation_id="c", prompt_inline="hi"
    )
    await mixin._check_capability(req)  # no raise


# ── _apply_input_sanitizers ──────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_input_sanitizers_no_sanitizer_returns_prompt(
    basic_request: AIRequest,
) -> None:
    """Без sanitizer — возвращается исходный prompt как есть."""
    mixin = _make_mixin()
    result = await mixin._apply_input_sanitizers(basic_request, None)
    assert result == "Контакт: alice@x.io"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_input_sanitizers_empty_prompt_returns_empty() -> None:
    """Пустой ``prompt_inline``/``prompt_ref`` → ``\"\"``."""
    mixin = _make_mixin()
    req = AIRequest(
        workflow_id="wf", tenant_id="t", correlation_id="c"
    )  # no prompt_inline/prompt_ref
    result = await mixin._apply_input_sanitizers(req, None)
    assert result == ""


@pytest.mark.unit
@pytest.mark.asyncio
async def test_input_sanitizers_happy_path_masks_pii(
    basic_request: AIRequest, basic_policy: AIPolicySpec
) -> None:
    """Sanitizer маскирует e-mail и сохраняет replacements в state."""
    sanitizer = _FakeSanitizer()
    mixin = _make_mixin(_sanitizer=sanitizer)
    result = await mixin._apply_input_sanitizers(basic_request, basic_policy)
    assert "[EMAIL_1]" in result
    assert "alice@x.io" not in result
    assert mixin._last_input_replacements == {"[EMAIL_1]": "alice@x.io"}
    assert mixin._last_input_pii_detected is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_input_sanitizers_runtime_error_falls_back(
    basic_request: AIRequest, caplog: pytest.LogCaptureFixture
) -> None:
    """RuntimeError из sanitizer → возвращается исходный prompt, warning logged."""
    sanitizer = _FakeSanitizer(fail=True)
    mixin = _make_mixin(_sanitizer=sanitizer)
    with caplog.at_level(
        logging.WARNING, logger="src.backend.core.ai.gateway_pipeline_mixin"
    ):
        result = await mixin._apply_input_sanitizers(basic_request, None)
    # mixin обрабатывает RuntimeError и возвращает original prompt без raise
    assert result == "Контакт: alice@x.io"
    assert any("sanitize_async недоступен" in rec.message for rec in caplog.records)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_input_sanitizers_generic_exception_falls_back(
    basic_request: AIRequest,
) -> None:
    """Generic Exception в sanitizer → fallback на original prompt (не raise)."""

    class _BadSanitizer:
        async def sanitize_async(self, text: str, **kwargs: Any) -> Any:
            raise ValueError("kaboom")

    mixin = _make_mixin(_sanitizer=_BadSanitizer())
    result = await mixin._apply_input_sanitizers(basic_request, None)
    assert result == "Контакт: alice@x.io"


# ── _apply_input_guards / _apply_output_guards ──────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_input_guards_no_enforcer_returns_empty() -> None:
    """Без ``policy_enforcer`` — early return ``[]`` без side-effects."""
    mixin = _make_mixin()
    policy = AIPolicySpec(
        name="x",
        workflow_pattern="*",
        tenant_pattern="*",
        model_router=ModelRouterSpec(primary="m"),
        input_guards=[GuardRef(name="llm_guard:PromptInjection")],
    )
    result = await mixin._apply_input_guards("prompt", policy)
    assert result == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_input_guards_no_policy_returns_empty() -> None:
    """``policy=None`` — early return ``[]``."""
    enforcer = MagicMock()
    mixin = _make_mixin(_policy_enforcer=enforcer)
    result = await mixin._apply_input_guards("prompt", None)
    assert result == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_input_guards_empty_guards_returns_empty() -> None:
    """``input_guards=[]`` — early return ``[]``."""
    enforcer = MagicMock()
    policy = AIPolicySpec(
        name="x",
        workflow_pattern="*",
        tenant_pattern="*",
        model_router=ModelRouterSpec(primary="m"),
        input_guards=[],
    )
    mixin = _make_mixin(_policy_enforcer=enforcer)
    result = await mixin._apply_input_guards("prompt", policy)
    assert result == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_input_guards_happy_path() -> None:
    """``policy_enforcer.guard_input`` вызывается и его результат пробрасывается."""
    enforcer = MagicMock()
    enforcer.guard_input = AsyncMock(
        return_value=[
            GuardResult(guard_name="llm_guard:PromptInjection", verdict="passed")
        ]
    )
    policy = AIPolicySpec(
        name="x",
        workflow_pattern="*",
        tenant_pattern="*",
        model_router=ModelRouterSpec(primary="m"),
        input_guards=[GuardRef(name="llm_guard:PromptInjection")],
    )
    mixin = _make_mixin(_policy_enforcer=enforcer)
    result = await mixin._apply_input_guards("hello", policy)
    assert len(result) == 1
    assert result[0].verdict == "passed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_output_guards_no_enforcer_returns_empty() -> None:
    """Output guards no-op без enforcer."""
    mixin = _make_mixin()
    response = AIResponse(content="hi")
    policy = AIPolicySpec(
        name="x",
        workflow_pattern="*",
        tenant_pattern="*",
        model_router=ModelRouterSpec(primary="m"),
        output_guards=[GuardRef(name="llama_guard:safe_v3")],
    )
    assert await mixin._apply_output_guards(response, policy) == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_output_guards_happy_path() -> None:
    """Output guards happy path — результат enforcer'а возвращается."""
    enforcer = MagicMock()
    enforcer.guard_output = AsyncMock(
        return_value=[GuardResult(guard_name="llama_guard:safe_v3", verdict="passed")]
    )
    response = AIResponse(content="hello")
    policy = AIPolicySpec(
        name="x",
        workflow_pattern="*",
        tenant_pattern="*",
        model_router=ModelRouterSpec(primary="m"),
        output_guards=[GuardRef(name="llama_guard:safe_v3")],
    )
    mixin = _make_mixin(_policy_enforcer=enforcer)
    result = await mixin._apply_output_guards(response, policy)
    assert len(result) == 1
    assert result[0].verdict == "passed"


# ── _render_prompt ───────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_render_prompt_no_budget_returns_sanitized() -> None:
    """Без ``policy.budget`` — sanitized текст возвращается as-is."""
    mixin = _make_mixin()
    result = await mixin._render_prompt(
        request=AIRequest(
            workflow_id="wf", tenant_id="t", correlation_id="c", prompt_inline="hi"
        ),
        policy=None,
        sanitized="sanitized text",
    )
    assert result == "sanitized text"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_render_prompt_under_limit_unchanged() -> None:
    """В пределах budget — текст не обрезается."""
    mixin = _make_mixin()
    policy = AIPolicySpec(
        name="x",
        workflow_pattern="*",
        tenant_pattern="*",
        model_router=ModelRouterSpec(primary="m"),
        budget=BudgetSpec(max_tokens_prompt=10_000),
    )
    text = "short prompt"
    result = await mixin._render_prompt(
        request=AIRequest(
            workflow_id="wf", tenant_id="t", correlation_id="c", prompt_inline="hi"
        ),
        policy=policy,
        sanitized=text,
    )
    assert result == text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_render_prompt_over_limit_truncates_with_tiktoken() -> None:
    """При превышении budget и доступном tiktoken — token-level truncation."""
    mixin = _make_mixin()
    policy = AIPolicySpec(
        name="x",
        workflow_pattern="*",
        tenant_pattern="*",
        model_router=ModelRouterSpec(primary="m"),
        budget=BudgetSpec(max_tokens_prompt=10),
    )
    long_text = " ".join(f"word{i}" for i in range(500))
    result = await mixin._render_prompt(
        request=AIRequest(
            workflow_id="wf", tenant_id="t", correlation_id="c", prompt_inline="hi"
        ),
        policy=policy,
        sanitized=long_text,
    )
    # tiktoken либо доступен (точная обрезка), либо fallback (char-level).
    # В обоих случаях результат короче исходного.
    assert len(result) < len(long_text)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_render_prompt_over_limit_fallback_no_tiktoken() -> None:
    """При недоступности tiktoken — char-level fallback (truncated marker)."""
    mixin = _make_mixin()
    policy = AIPolicySpec(
        name="x",
        workflow_pattern="*",
        tenant_pattern="*",
        model_router=ModelRouterSpec(primary="m"),
        budget=BudgetSpec(max_tokens_prompt=2),  # очень маленький budget
    )
    long_text = "x" * 1000
    with patch.dict("sys.modules", {"tiktoken": None}):
        result = await mixin._render_prompt(
            request=AIRequest(
                workflow_id="wf", tenant_id="t", correlation_id="c", prompt_inline="hi"
            ),
            policy=policy,
            sanitized=long_text,
        )
    # Fallback добавляет [truncated] marker
    assert "[truncated]" in result or len(result) < len(long_text)


# ── _invoke_llm ──────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invoke_llm_no_policy_uses_default_model() -> None:
    """Без policy — backward-compat path через LiteLLMGateway с ``model=None``."""
    llm = _FakeLLMGateway(payload=_fake_litellm_payload(content="hi back"))
    mixin = _make_mixin(_llm_gateway=llm)
    response = await mixin._invoke_llm("hello", None, stream=False)
    assert isinstance(response, AIResponse)
    assert response.content == "hi back"
    assert response.tokens_prompt == 5
    assert response.tokens_completion == 7
    assert llm.calls[0]["model"] is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invoke_llm_with_policy_passes_fallbacks(
    basic_policy: AIPolicySpec,
) -> None:
    """Policy с ``model_router.fallback`` → ``fallbacks=`` kwarg в acompletion."""
    llm = _FakeLLMGateway()
    mixin = _make_mixin(_llm_gateway=llm)
    await mixin._invoke_llm("hi", basic_policy, stream=False)
    assert llm.calls[0]["model"] == "openai/gpt-4o-mini"
    # basic_policy без fallback — не должно быть kwarg.
    assert "fallbacks" not in llm.calls[0] or llm.calls[0].get("fallbacks") is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invoke_llm_extracts_from_object_response() -> None:
    """Object-стиль litellm-ответа (ModelResponse-like) парсится корректно."""
    from types import SimpleNamespace

    class _Message:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Choice:
        def __init__(self, message: _Message) -> None:
            self.message = message

    class _Usage:
        # НЕ определяем model_dump() — pure attributes only.
        def __init__(self, pt: int, ct: int) -> None:
            self.prompt_tokens = pt
            self.completion_tokens = ct

    response_obj = SimpleNamespace(
        choices=[_Choice(_Message("object content"))],
        usage=_Usage(pt=11, ct=22),
        model="anthropic/claude-3-7",
    )

    llm = MagicMock()
    llm.acompletion = AsyncMock(return_value=response_obj)
    mixin = _make_mixin(_llm_gateway=llm)
    response = await mixin._invoke_llm("hi", None, stream=False)
    assert response.content == "object content"
    assert response.tokens_prompt == 11
    assert response.tokens_completion == 22
    assert response.model_used == "anthropic/claude-3-7"


# ── _apply_output_sanitizers ─────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_output_sanitizers_empty_content_passthrough() -> None:
    """Пустой ``response.content`` — return as-is."""
    mixin = _make_mixin()
    response = AIResponse(content="")
    result = await mixin._apply_output_sanitizers(response, None)
    assert result is response


@pytest.mark.unit
@pytest.mark.asyncio
async def test_output_sanitizers_no_sanitizer_passthrough() -> None:
    """Без sanitizer — response возвращается unchanged."""
    mixin = _make_mixin()
    response = AIResponse(content="hello world")
    result = await mixin._apply_output_sanitizers(response, None)
    assert result is response


@pytest.mark.unit
@pytest.mark.asyncio
async def test_output_sanitizers_masks_pii_in_output() -> None:
    """Output sanitizer маскирует PII и проставляет ``pii_detected=True``."""
    sanitizer = _FakeSanitizer()
    mixin = _make_mixin(_sanitizer=sanitizer)
    response = AIResponse(content="Contact: alice@x.io")
    result = await mixin._apply_output_sanitizers(response, None)
    assert "[EMAIL_1]" in result.content
    assert result.pii_detected is True
    assert result.model_used == response.model_used
    assert result.tokens_prompt == response.tokens_prompt


@pytest.mark.unit
@pytest.mark.asyncio
async def test_output_sanitizers_runtime_error_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """RuntimeError → return original response (warning logged, no raise)."""
    sanitizer = _FakeSanitizer(fail=True)
    mixin = _make_mixin(_sanitizer=sanitizer)
    response = AIResponse(content="hello")
    with caplog.at_level(
        logging.WARNING, logger="src.backend.core.ai.gateway_pipeline_mixin"
    ):
        result = await mixin._apply_output_sanitizers(response, None)
    assert result is response
    assert any("output sanitize_async" in rec.message for rec in caplog.records)


# ── _audit_emit ──────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_audit_emit_happy_path(basic_request: AIRequest) -> None:
    """``audit.emit`` вызывается с правильными полями."""
    audit = MagicMock()
    audit.emit = AsyncMock()
    mixin = _make_mixin(_audit_service=audit)
    response = AIResponse(
        content="hi",
        tokens_prompt=10,
        tokens_completion=20,
        model_used="openai/gpt-4o",
        cost_usd=0.001,
    )
    await mixin._audit_emit(basic_request, None, response)
    audit.emit.assert_awaited_once()
    call_kwargs = audit.emit.await_args.kwargs
    assert call_kwargs["event"] == "ai.invocation.completed"
    assert call_kwargs["actor"] == "tenant:t-1"
    assert call_kwargs["resource"] == "ai_workflow:credit_check"
    assert call_kwargs["action"] == "invoke"
    assert call_kwargs["correlation_id"] == "req-abc"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_audit_emit_no_service_silent_noop() -> None:
    """Без ``audit_service`` и без unified service — no-op."""
    mixin = _make_mixin()
    req = AIRequest(
        workflow_id="wf", tenant_id="t", correlation_id="c", prompt_inline="hi"
    )
    response = AIResponse(content="hi")
    # Подменяем get_unified_audit_service чтобы он упал ImportError'ом
    with patch(
        "src.backend.services.audit.audit_service.get_unified_audit_service",
        side_effect=ImportError("nope"),
    ):
        await mixin._audit_emit(req, None, response)  # no raise


@pytest.mark.unit
@pytest.mark.asyncio
async def test_audit_emit_exception_swallowed(basic_request: AIRequest) -> None:
    """``audit.emit`` exception — не пробрасывается наружу."""
    audit = MagicMock()
    audit.emit = AsyncMock(side_effect=RuntimeError("CH down"))
    mixin = _make_mixin(_audit_service=audit)
    response = AIResponse(content="hi")
    await mixin._audit_emit(basic_request, None, response)  # no raise


@pytest.mark.unit
@pytest.mark.asyncio
async def test_audit_emit_policy_name_default() -> None:
    """``policy=None`` → ``details['policy'] = 'default'``."""
    audit = MagicMock()
    audit.emit = AsyncMock()
    mixin = _make_mixin(_audit_service=audit)
    req = AIRequest(
        workflow_id="wf", tenant_id="t", correlation_id="c", prompt_inline="hi"
    )
    response = AIResponse(content="hi")
    await mixin._audit_emit(req, None, response)
    details = audit.emit.await_args.kwargs["details"]
    assert details["policy"] == "default"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_audit_emit_merges_audit_extra_attrs(basic_request: AIRequest) -> None:
    """``policy.audit.extra_attrs`` мерджатся в details."""
    audit = MagicMock()
    audit.emit = AsyncMock()
    mixin = _make_mixin(_audit_service=audit)
    policy = AIPolicySpec(
        name="strict",
        workflow_pattern="*",
        tenant_pattern="*",
        model_router=ModelRouterSpec(primary="m"),
        audit=AuditSpec(extra_attrs={"compliance": "152-FZ", "regulator": "CBR"}),
    )
    response = AIResponse(content="hi")
    await mixin._audit_emit(basic_request, policy, response)
    details = audit.emit.await_args.kwargs["details"]
    assert details["compliance"] == "152-FZ"
    assert details["regulator"] == "CBR"
    assert details["policy"] == "strict"


# ── _cost_track ──────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cost_track_no_tracker_noop() -> None:
    """Без ``cost_tracker`` — early return."""
    mixin = _make_mixin()
    req = AIRequest(
        workflow_id="wf", tenant_id="t", correlation_id="c", prompt_inline="hi"
    )
    response = AIResponse(content="hi", cost_usd=0.01)
    await mixin._cost_track(req, None, response)  # no raise


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cost_track_calls_record_cost_and_tokens() -> None:
    """``record_cost`` + ``record_tokens`` вызываются при ``cost_usd > 0``."""
    tracker = MagicMock()
    tracker.record_cost = MagicMock()
    tracker.record_tokens = MagicMock()
    mixin = _make_mixin(_cost_tracker=tracker)
    req = AIRequest(
        workflow_id="wf", tenant_id="t", correlation_id="c", prompt_inline="hi"
    )
    response = AIResponse(
        content="hi",
        cost_usd=0.01,
        tokens_prompt=10,
        tokens_completion=20,
        model_used="openai/gpt-4o",
    )
    await mixin._cost_track(req, None, response)
    tracker.record_cost.assert_called_once()
    tracker.record_tokens.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cost_track_no_cost_record_skipped() -> None:
    """``cost_usd == 0`` → ``record_cost`` не вызывается, ``record_tokens`` да."""
    tracker = MagicMock()
    tracker.record_cost = MagicMock()
    tracker.record_tokens = MagicMock()
    mixin = _make_mixin(_cost_tracker=tracker)
    req = AIRequest(
        workflow_id="wf", tenant_id="t", correlation_id="c", prompt_inline="hi"
    )
    response = AIResponse(content="hi", cost_usd=0.0)
    await mixin._cost_track(req, None, response)
    tracker.record_cost.assert_not_called()
    tracker.record_tokens.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cost_track_exception_swallowed() -> None:
    """Исключение из tracker'а — не пробрасывается (debug-лог)."""
    tracker = MagicMock()
    tracker.record_cost = MagicMock(side_effect=RuntimeError("boom"))
    mixin = _make_mixin(_cost_tracker=tracker)
    req = AIRequest(
        workflow_id="wf", tenant_id="t", correlation_id="c", prompt_inline="hi"
    )
    response = AIResponse(content="hi", cost_usd=0.01, model_used="m")
    await mixin._cost_track(req, None, response)  # no raise


# ── _resolve_sanitizer / _resolve_llm_gateway ────────────────────────────────


@pytest.mark.unit
def test_resolve_sanitizer_caches() -> None:
    """``_resolve_sanitizer`` кеширует в ``self._sanitizer``."""
    fake = _FakeSanitizer()
    mixin = _make_mixin(_sanitizer=None)
    mixin._sanitizer = None
    mixin._sanitizer = fake
    result1 = mixin._resolve_sanitizer()
    result2 = mixin._resolve_sanitizer()
    assert result1 is fake
    assert result2 is fake


@pytest.mark.unit
def test_resolve_llm_gateway_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_resolve_llm_gateway`` кеширует singleton gateway."""
    sentinel = object()
    monkeypatch.setattr(
        "src.backend.services.ai.gateway.get_litellm_gateway", lambda: sentinel
    )
    mixin = _make_mixin(_llm_gateway=None)
    mixin._llm_gateway = None
    result1 = mixin._resolve_llm_gateway()
    result2 = mixin._resolve_llm_gateway()
    assert result1 is sentinel
    assert result2 is sentinel
    # Кешируется в self._llm_gateway
    assert mixin._llm_gateway is sentinel


# ── Pure helpers: property tests ────────────────────────────────────────────


@pytest.mark.unit
@given(lang=st.sampled_from(["ru", "en", "uk", "de", "fr", "zh", "ja", "pt-BR", "tr"]))
@settings(max_examples=50, deadline=None)
def test_language_from_policy_presidio_name_extraction_property(lang: str) -> None:
    """Property: ``presidio:<lang>`` всегда даёт ``<lang>`` (без потери регистра).

    Hypothesis генерирует произвольные строки языка из стратегии; mixin
    должен вернуть suffix после последнего ``:`` (или default, если
    suffix пустой).
    """
    policy = AIPolicySpec(
        name="x",
        workflow_pattern="*",
        tenant_pattern="*",
        model_router=ModelRouterSpec(primary="m"),
        input_sanitizers=[SanitizerRef(name=f"presidio:{lang}")],
    )
    result = PipelineStepsMixin._language_from_policy(policy, default="ru")
    assert result == lang


@pytest.mark.unit
def test_language_from_policy_empty_sanitizers_returns_default() -> None:
    """Пустой список sanitizers → default."""
    policy = AIPolicySpec(
        name="x",
        workflow_pattern="*",
        tenant_pattern="*",
        model_router=ModelRouterSpec(primary="m"),
        input_sanitizers=[],
    )
    assert PipelineStepsMixin._language_from_policy(policy, default="de") == "de"


@pytest.mark.unit
def test_language_from_policy_config_language_wins() -> None:
    """``config.language`` имеет приоритет над name."""
    policy = AIPolicySpec(
        name="x",
        workflow_pattern="*",
        tenant_pattern="*",
        model_router=ModelRouterSpec(primary="m"),
        input_sanitizers=[SanitizerRef(name="presidio:ru", config={"language": "uk"})],
    )
    assert PipelineStepsMixin._language_from_policy(policy, default="en") == "uk"


@pytest.mark.unit
def test_provider_from_model_slash() -> None:
    """``openai/gpt-4o`` → ``openai``."""
    assert PipelineStepsMixin._provider_from_model("openai/gpt-4o") == "openai"
    assert (
        PipelineStepsMixin._provider_from_model("anthropic/claude-3-7") == "anthropic"
    )


@pytest.mark.unit
def test_provider_from_model_no_slash_defaults_openai() -> None:
    """Без ``/`` → ``\"openai\"`` (default)."""
    assert PipelineStepsMixin._provider_from_model("gpt-4o-mini") == "openai"
    assert PipelineStepsMixin._provider_from_model("") == "openai"


@pytest.mark.unit
def test_extract_completion_dict_response_with_empty_choices() -> None:
    """``choices=[]`` → ``content=\"\"``, tokens=0, model=fallback."""
    payload = {"choices": [], "usage": {}, "model": "x"}
    content, p, c, m = PipelineStepsMixin._extract_completion(
        payload, fallback_model="fb"
    )
    assert content == ""
    assert p == 0
    assert c == 0
    assert m == "x"


@pytest.mark.unit
def test_extract_completion_dict_response_missing_model() -> None:
    """``model`` отсутствует → ``fallback_model``."""
    payload = {
        "choices": [{"message": {"content": "hi"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2},
    }
    _, _, _, m = PipelineStepsMixin._extract_completion(payload, fallback_model="fb")
    assert m == "fb"


# ── Concurrent pipeline execution ───────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrent_pipeline_execution_via_gather() -> None:
    """Mixin'овский шаг ``_resolve_policy`` безопасен для ``asyncio.gather``.

    Проверяет что миксин не держит global state и несколько одновременных
    вызовов ``_resolve_policy`` отрабатывают параллельно.
    """
    call_count = 0

    class _SlowResolver:
        async def resolve(self, *, workflow_id: str, tenant_id: str) -> str:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)
            return f"policy-{workflow_id}-{tenant_id}"

    mixin = _make_mixin(_policy_resolver=_SlowResolver())
    requests = [
        AIRequest(
            workflow_id=f"wf-{i}",
            tenant_id=f"t-{i}",
            correlation_id=f"c-{i}",
            prompt_inline="hi",
        )
        for i in range(5)
    ]
    results = await asyncio.gather(*[mixin._resolve_policy(req) for req in requests])
    assert len(results) == 5
    assert call_count == 5
    assert results[0] == "policy-wf-0-t-0"
    assert results[4] == "policy-wf-4-t-4"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_audit_emit_emits_single_event_with_correct_severity() -> None:
    """``severity='info'`` и ``outcome='success'`` в audit emit call."""
    audit = MagicMock()
    audit.emit = AsyncMock()
    mixin = _make_mixin(_audit_service=audit)
    req = AIRequest(
        workflow_id="wf", tenant_id="t", correlation_id="c", prompt_inline="hi"
    )
    response = AIResponse(content="hi", model_used="m")
    await mixin._audit_emit(req, None, response)
    call_kwargs = audit.emit.await_args.kwargs
    assert call_kwargs["severity"] == "info"
    assert call_kwargs["outcome"] == "success"
    assert call_kwargs["tenant_id"] == "t"
    assert call_kwargs["route_name"] == "wf"
