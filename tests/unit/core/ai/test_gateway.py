"""Targeted unit-тесты на 3 метода :class:`AIGateway` из Task 2.

Покрывают:

* :meth:`AIGateway._apply_input_sanitizers` — шаг 3 (Presidio PII mask);
* :meth:`AIGateway._apply_output_sanitizers` — шаг 8 (Presidio PII mask
  на ответе LLM);
* :meth:`AIGateway._audit_emit` — шаг 9a (Unified AuditService emit).

Каждый метод проверяется изолированно от полного pipeline через прямой
вызов с подготовленным AIRequest / AIResponse / AIPolicySpec — без feature-flag
переключений и без LiteLLMGateway, чтобы изолировать поведение конкретного
шага. End-to-end pipeline покрыт ``test_gateway_pipeline.py``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.ai import AIGateway, AIRequest, AIResponse
from src.backend.core.ai.policy.spec import (
    AIPolicySpec,
    AuditSpec,
    ModelRouterSpec,
    SanitizerRef,
)


class _FakeSanitizerResult:
    """Stand-in для :class:`SanitizationResult` (duck-typed по полям)."""

    def __init__(self, sanitized_text: str, replacements: dict[str, str]) -> None:
        self.sanitized_text = sanitized_text
        self.replacements = replacements


class _FakeSanitizer:
    """Фейковый async-sanitizer с настраиваемым поведением.

    По умолчанию маскирует ``alice@x.io`` → ``[EMAIL_1]``. Может быть
    сконфигурирован на raise ``RuntimeError`` (Presidio недоступен) либо
    произвольное исключение.
    """

    def __init__(
        self, *, raise_runtime: bool = False, raise_unexpected: bool = False
    ) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self._raise_runtime = raise_runtime
        self._raise_unexpected = raise_unexpected

    async def sanitize_async(
        self, text: str, *, language: str | None = None
    ) -> _FakeSanitizerResult:
        self.calls.append((text, language))
        if self._raise_runtime:
            raise RuntimeError("Presidio недоступен")
        if self._raise_unexpected:
            raise ValueError("боль")
        if "alice@x.io" in text:
            return _FakeSanitizerResult(
                sanitized_text=text.replace("alice@x.io", "[EMAIL_1]"),
                replacements={"[EMAIL_1]": "alice@x.io"},
            )
        return _FakeSanitizerResult(sanitized_text=text, replacements={})


def _make_policy(
    *, sanitizer_language: str | None = None, audit_extra: dict[str, str] | None = None
) -> AIPolicySpec:
    """Удобный конструктор минимально-валидной AIPolicySpec."""
    input_sanitizers: list[SanitizerRef] = []
    if sanitizer_language is not None:
        input_sanitizers.append(SanitizerRef(name=f"presidio:{sanitizer_language}"))
    return AIPolicySpec(
        name="test_policy",
        workflow_pattern="*",
        tenant_pattern="*",
        model_router=ModelRouterSpec(primary="openai/gpt-4o-mini"),
        input_sanitizers=input_sanitizers,
        audit=AuditSpec(extra_attrs=dict(audit_extra or {})),
        required=False,
    )


# ─── _apply_input_sanitizers ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_input_sanitizers_mask_pii_in_prompt() -> None:
    """PII в ``prompt_inline`` заменяется на placeholder из sanitizer."""
    sanitizer = _FakeSanitizer()
    gateway = AIGateway(sanitizer=sanitizer)
    request = AIRequest(
        workflow_id="wf",
        tenant_id="t-1",
        correlation_id="req-1",
        prompt_inline="Контакт: alice@x.io",
    )

    result = await gateway._apply_input_sanitizers(request, policy=None)

    assert result == "Контакт: [EMAIL_1]"
    assert sanitizer.calls == [("Контакт: alice@x.io", "ru")]
    # gateway запоминает PII-state для последующей сборки AIResponse
    assert gateway._last_input_pii_detected is True
    assert gateway._last_input_replacements == {"[EMAIL_1]": "alice@x.io"}


@pytest.mark.asyncio
async def test_input_sanitizers_returns_empty_for_blank_prompt() -> None:
    """Пустой prompt не вызывает sanitizer и возвращается как есть."""
    sanitizer = _FakeSanitizer()
    gateway = AIGateway(sanitizer=sanitizer)
    request = AIRequest(workflow_id="wf", tenant_id="t-1", correlation_id="req-1")

    result = await gateway._apply_input_sanitizers(request, policy=None)

    assert result == ""
    assert sanitizer.calls == []


@pytest.mark.asyncio
async def test_input_sanitizers_passthrough_when_sanitizer_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без sanitizer'а и при недоступном Presidio-фабрике prompt не меняется."""
    # Закрываем lazy-резолв Presidio-фабрики, чтобы не уходить в реальный модуль.
    gateway = AIGateway(sanitizer=None)
    monkeypatch.setattr(gateway, "_resolve_sanitizer", lambda: None)

    request = AIRequest(
        workflow_id="wf",
        tenant_id="t-1",
        correlation_id="req-1",
        prompt_inline="raw text",
    )
    result = await gateway._apply_input_sanitizers(request, policy=None)
    assert result == "raw text"


@pytest.mark.asyncio
async def test_input_sanitizers_handles_runtime_error_gracefully() -> None:
    """Если Presidio raise RuntimeError — возвращается исходный prompt."""
    sanitizer = _FakeSanitizer(raise_runtime=True)
    gateway = AIGateway(sanitizer=sanitizer)
    request = AIRequest(
        workflow_id="wf",
        tenant_id="t-1",
        correlation_id="req-1",
        prompt_inline="any text",
    )

    result = await gateway._apply_input_sanitizers(request, policy=None)

    assert result == "any text"


@pytest.mark.asyncio
async def test_input_sanitizers_handles_unexpected_exception_gracefully() -> None:
    """Любая иная ошибка sanitizer'а не ломает шаг (логируется, возврат исходного)."""
    sanitizer = _FakeSanitizer(raise_unexpected=True)
    gateway = AIGateway(sanitizer=sanitizer)
    request = AIRequest(
        workflow_id="wf", tenant_id="t-1", correlation_id="req-1", prompt_inline="any"
    )

    result = await gateway._apply_input_sanitizers(request, policy=None)
    assert result == "any"


@pytest.mark.asyncio
async def test_input_sanitizers_uses_language_from_policy() -> None:
    """``presidio:en`` в policy.input_sanitizers → language='en' в вызове."""
    sanitizer = _FakeSanitizer()
    gateway = AIGateway(sanitizer=sanitizer)
    policy = _make_policy(sanitizer_language="en")
    request = AIRequest(
        workflow_id="wf", tenant_id="t-1", correlation_id="req-1", prompt_inline="hello"
    )

    await gateway._apply_input_sanitizers(request, policy=policy)
    assert sanitizer.calls == [("hello", "en")]


# ─── _apply_output_sanitizers ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_output_sanitizers_mask_pii_in_response_content() -> None:
    """PII в content ответа LLM маскируется + pii_detected=True."""
    sanitizer = _FakeSanitizer()
    gateway = AIGateway(sanitizer=sanitizer)
    response = AIResponse(
        content="Ответ: alice@x.io",
        tokens_prompt=3,
        tokens_completion=5,
        model_used="openai/gpt-4o-mini",
    )

    result = await gateway._apply_output_sanitizers(response, policy=None)

    assert result.content == "Ответ: [EMAIL_1]"
    assert result.pii_detected is True
    # метаданные ответа не теряются
    assert result.tokens_prompt == 3
    assert result.tokens_completion == 5
    assert result.model_used == "openai/gpt-4o-mini"


@pytest.mark.asyncio
async def test_output_sanitizers_skip_when_content_empty() -> None:
    """Если ``response.content`` пустой — sanitizer не вызывается."""
    sanitizer = _FakeSanitizer()
    gateway = AIGateway(sanitizer=sanitizer)
    response = AIResponse(content="")

    result = await gateway._apply_output_sanitizers(response, policy=None)

    assert result is response
    assert sanitizer.calls == []


@pytest.mark.asyncio
async def test_output_sanitizers_passthrough_when_sanitizer_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без sanitizer'а возвращается исходный response без модификаций."""
    gateway = AIGateway(sanitizer=None)
    monkeypatch.setattr(gateway, "_resolve_sanitizer", lambda: None)
    response = AIResponse(content="raw output")

    result = await gateway._apply_output_sanitizers(response, policy=None)
    assert result is response


@pytest.mark.asyncio
async def test_output_sanitizers_handles_runtime_error_gracefully() -> None:
    """RuntimeError sanitizer'а на output не ломает pipeline."""
    sanitizer = _FakeSanitizer(raise_runtime=True)
    gateway = AIGateway(sanitizer=sanitizer)
    response = AIResponse(content="content")

    result = await gateway._apply_output_sanitizers(response, policy=None)
    assert result is response


@pytest.mark.asyncio
async def test_output_sanitizers_inherit_input_pii_flag() -> None:
    """Если PII задетектен на input — pii_detected остаётся True на output."""
    sanitizer = _FakeSanitizer()
    gateway = AIGateway(sanitizer=sanitizer)
    # эмулируем последствия шага 3 (PII был найден на input)
    gateway._last_input_pii_detected = True

    response = AIResponse(content="Чистый ответ без PII")
    result = await gateway._apply_output_sanitizers(response, policy=None)

    # output sanitizer не нашёл PII, но флаг наследуется от input
    assert result.pii_detected is True
    assert result.content == "Чистый ответ без PII"


@pytest.mark.asyncio
async def test_output_sanitizers_uses_language_from_policy() -> None:
    """policy.input_sanitizers[0] определяет язык для output sanitize."""
    sanitizer = _FakeSanitizer()
    gateway = AIGateway(sanitizer=sanitizer)
    policy = _make_policy(sanitizer_language="en")
    response = AIResponse(content="text")

    await gateway._apply_output_sanitizers(response, policy=policy)
    assert sanitizer.calls == [("text", "en")]


# ─── _audit_emit ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_emit_uses_injected_service() -> None:
    """Эмит вызывается с правильными полями на инжектированном AuditService."""
    audit = MagicMock()
    audit.emit = AsyncMock()
    gateway = AIGateway(audit_service=audit)
    request = AIRequest(
        workflow_id="credit_check", tenant_id="t-premium", correlation_id="req-xyz"
    )
    response = AIResponse(
        content="ok",
        tokens_prompt=10,
        tokens_completion=15,
        cost_usd=0.002,
        model_used="openai/gpt-4o-mini",
        pii_detected=True,
        guardrails_verdict={"input": "safe", "output": "safe"},
    )

    await gateway._audit_emit(request, policy=None, response=response)

    audit.emit.assert_awaited_once()
    kwargs = audit.emit.await_args.kwargs
    assert kwargs["event"] == "ai.invocation.completed"
    assert kwargs["actor"] == "tenant:t-premium"
    assert kwargs["resource"] == "ai_workflow:credit_check"
    assert kwargs["action"] == "invoke"
    assert kwargs["outcome"] == "success"
    assert kwargs["severity"] == "info"
    assert kwargs["correlation_id"] == "req-xyz"
    assert kwargs["tenant_id"] == "t-premium"
    assert kwargs["route_name"] == "credit_check"
    details = kwargs["details"]
    assert details["workflow_id"] == "credit_check"
    assert details["policy"] == "default"  # policy=None → "default"
    assert details["model_used"] == "openai/gpt-4o-mini"
    assert details["tokens_prompt"] == 10
    assert details["tokens_completion"] == 15
    assert details["cost_usd"] == 0.002
    assert details["pii_detected"] is True
    assert details["guardrails_verdict"] == {"input": "safe", "output": "safe"}


@pytest.mark.asyncio
async def test_audit_emit_includes_policy_name_and_extra_attrs() -> None:
    """Имя policy и ``audit.extra_attrs`` попадают в details."""
    audit = MagicMock()
    audit.emit = AsyncMock()
    gateway = AIGateway(audit_service=audit)
    policy = _make_policy(audit_extra={"compliance": "152-FZ", "domain": "credit"})
    request = AIRequest(workflow_id="wf", tenant_id="t-1", correlation_id="req-1")
    response = AIResponse(content="ok")

    await gateway._audit_emit(request, policy=policy, response=response)

    audit.emit.assert_awaited_once()
    details = audit.emit.await_args.kwargs["details"]
    assert details["policy"] == "test_policy"
    assert details["compliance"] == "152-FZ"
    assert details["domain"] == "credit"


@pytest.mark.asyncio
async def test_audit_emit_resolves_singleton_when_service_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При ``audit_service=None`` резолвится :func:`get_unified_audit_service`."""
    fake_audit = MagicMock()
    fake_audit.emit = AsyncMock()

    import src.backend.core.audit.facade.audit_service as audit_module

    monkeypatch.setattr(audit_module, "get_unified_audit_service", lambda: fake_audit)

    gateway = AIGateway(audit_service=None)
    request = AIRequest(workflow_id="wf", tenant_id="t-1", correlation_id="req-1")
    response = AIResponse(content="ok")

    await gateway._audit_emit(request, policy=None, response=response)
    fake_audit.emit.assert_awaited_once()


@pytest.mark.asyncio
async def test_audit_emit_swallows_singleton_lookup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если резолв singleton'а падает — emit просто no-op (не ломает invoke)."""
    import src.backend.core.audit.facade.audit_service as audit_module

    def _boom() -> Any:
        raise RuntimeError("AuditService недоступен")

    monkeypatch.setattr(audit_module, "get_unified_audit_service", _boom)

    gateway = AIGateway(audit_service=None)
    request = AIRequest(workflow_id="wf", tenant_id="t-1", correlation_id="req-1")
    response = AIResponse(content="ok")

    # не должно raise
    await gateway._audit_emit(request, policy=None, response=response)


@pytest.mark.asyncio
async def test_audit_emit_swallows_emit_exception() -> None:
    """Исключение из ``audit.emit`` не ломает pipeline."""
    audit = MagicMock()
    audit.emit = AsyncMock(side_effect=RuntimeError("CH down"))
    gateway = AIGateway(audit_service=audit)
    request = AIRequest(workflow_id="wf", tenant_id="t-1", correlation_id="req-1")
    response = AIResponse(content="ok")

    # не должно raise
    await gateway._audit_emit(request, policy=None, response=response)
    audit.emit.assert_awaited_once()
