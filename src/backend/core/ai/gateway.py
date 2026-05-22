"""AIGateway — единая точка входа в AI (ADR-NEW-19, Sprint 25 W1).

Назначение
----------
Единственная разрешённая точка входа в LLM-вызов в проекте, по аналогии
с :class:`OutboundHttpClient` для HTTP (ADR-0050) и
:class:`AuthorizationGateway` для auth (ADR-NEW-1).

Закрывает 3 параллельных кодопути LLM:

* ``services/ai/ai_graph.py`` — LangGraph ReAct;
* ``services/ai/agents_pydantic/base.py`` — PydanticAI;
* ``services/ai/ai_agent.py`` — ручной fallback chain.

Pipeline (9 шагов)
------------------
1. ``PolicyResolver`` → :class:`AIPolicySpec` по ``workflow_id`` + ``tenant_id``.
2. ``CapabilityGate`` intercept: ``ai.invoke.<workflow_id>``.
3. Input sanitizers (PII через PIITokenizer из S25 W4 + Presidio из S24 W1).
4. Input guards (NeMo Colang из S24 W2 + Rebuff/Lakera).
5. ``PromptRenderer`` (Langfuse PromptRegistry + tiktoken budget trim).
6. ``ModelRouter`` (LiteLLM primary + fallback chain).
7. Output guards (Llama Guard 3 из S24 W2).
8. Output sanitizers (Presidio + JSONSchema через Outlines).
9. Audit + Cost (Unified AuditService из S17/K3 + Langfuse v3 OTel из S25 W5).

Feature-flag
------------
:envvar:`FEATURE_AI_GATEWAY_ENFORCE` (default-OFF, см. ADR-NEW-19).

При ``False`` — :meth:`AIGateway.invoke` работает в **pass-through** режиме:
делегирует вызов в ``_legacy_invoke()`` без enforcement. Все 3 кодопути LLM
сохраняют существующий интерфейс (backward-compat).

При ``True`` (после S27 closure) — 100% LLM-вызовов через :class:`AIGateway`,
обходные пути блокируются ``check_ai_gateway_coverage`` AST-checker'ом.

Capability
----------
``ai.invoke.<workflow_id>`` — capability обязательна при ``enforce=True``;
регистрируется в :mod:`core.security.capabilities.vocabulary`.

См. также
---------
* :class:`AIPolicySpec` — :mod:`core.ai.policy.spec` (ADR-NEW-20).
* :class:`PolicyResolver` — :mod:`core.ai.policy.resolver` (ADR-NEW-20).
* :class:`PIITokenizer` — :mod:`core.security.pii_tokenizer` (ADR-NEW-21).
* :class:`SkillRegistry` — :mod:`core.ai.skill_registry` (ADR-NEW-22).
* docs/adr/0066-ai-gateway-facade.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.core.ai.policy.spec import AIPolicySpec

__all__ = ("AIGateway", "AIRequest", "AIResponse")


@dataclass(frozen=True, slots=True)
class AIRequest:
    """Запрос на AI-инвокацию.

    Передаётся в :meth:`AIGateway.invoke`. Поля заполняются caller'ом из
    :class:`RequestContext` (ADR-NEW-3) — ``correlation_id`` и ``tenant_id``
    обязательны для аудит-связки.

    Attributes:
        workflow_id: Логический идентификатор бизнес-операции
            (``"credit_check"``, ``"doc_summarize"``). Используется
            :class:`PolicyResolver` для подбора :class:`AIPolicySpec`.
        tenant_id: Tenant из ``TenantContext``; контекст PII / quotas / SLO.
        correlation_id: Идентификатор запроса из ``RequestContext`` для
            аудит-trace; пробрасывается во все sinks (ClickHouse, Langfuse).
        prompt_ref: Ссылка на промпт в Langfuse PromptRegistry
            (``"credit_check.production"``). Взаимоисключаемо с ``prompt_inline``.
        prompt_inline: Inline-промпт без registry-маршрутизации (deprecated
            путь для legacy кодопутей; S27 closure → запрещено).
        context: Переменные подстановки в template (Jinja2 / f-string).
        stream: Если ``True`` — стриминг chunks (SSE/WebSocket).
    """

    workflow_id: str
    tenant_id: str
    correlation_id: str
    prompt_ref: str | None = None
    prompt_inline: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    stream: bool = False


@dataclass(frozen=True, slots=True)
class AIResponse:
    """Результат AI-инвокации.

    Attributes:
        content: Финальный (sanitized) текст ответа LLM.
        structured: Опциональный Pydantic-объект, если использован
            Instructor / Outlines structured output.
        tokens_prompt: Токены входа после template-render и budget-trim.
        tokens_completion: Токены ответа LLM.
        cost_usd: Стоимость инвокации в USD (через ``ai_cost_tracker``).
        model_used: Фактическая модель, выбранная ``ModelRouter`` из
            fallback chain (может отличаться от ``policy.model_router.primary``).
        pii_detected: ``True`` если хотя бы один PII entity обнаружен
            на стадии input/output sanitizers.
        guardrails_verdict: ``{"input": "safe", "output": "safe|blocked|warn"}``
            от input/output guards (NeMo + Llama Guard).
    """

    content: str
    structured: Any | None = None
    tokens_prompt: int = 0
    tokens_completion: int = 0
    cost_usd: float = 0.0
    model_used: str = ""
    pii_detected: bool = False
    guardrails_verdict: dict[str, str] = field(default_factory=dict)


class AIGateway:
    """Фасад — единая точка входа в AI (ADR-NEW-19).

    Использование::

        gateway = AIGateway(
            policy_resolver=resolver,
            capability_gate=gate,
            audit_service=audit,
        )
        response = await gateway.invoke(
            AIRequest(
                workflow_id="credit_check",
                tenant_id="credit_premium",
                correlation_id="req-abc-123",
                prompt_ref="credit_check.production",
                context={"score": 750, "history": [...]},
            )
        )

    Pass-through (scaffold)
    -----------------------
    При :data:`feature_flags.ai_gateway_enforce = False` (default) метод
    :meth:`invoke` делегирует в ``_legacy_invoke()`` без пайплайна
    защитных слоёв — это backward-compat для 3 существующих кодопутей.
    Реальная реализация шагов 1-9 — в Wave S25 W1..W5 + S27 W2..W5.

    Замечание (BUSY EVOLUTION)
    --------------------------
    Этот scaffold НАМЕРЕННО оставляет ``_apply_*`` методы как
    ``NotImplementedError`` — это указатели на будущие wave (S25 W4 PIITokenizer,
    S24 W2 NeMo Guardrails, и т. д.). Не использовать в production до
    переключения feature-flag в S27 closure.

    См. ADR-0066 раздел «DoD-критерии scaffold → Accepted».
    """

    def __init__(
        self,
        *,
        policy_resolver: Any | None = None,
        capability_gate: Any | None = None,
        audit_service: Any | None = None,
        cost_tracker: Any | None = None,
    ) -> None:
        """Инициализация фасада.

        Args:
            policy_resolver: :class:`core.ai.policy.resolver.PolicyResolver`;
                при ``None`` используется fallback policy ``"default"``
                (``required=False``).
            capability_gate: ``CapabilityGate.check`` для проверки
                ``ai.invoke.<workflow_id>``; при ``None`` — no-op (allow-all).
            audit_service: Unified ``AuditService`` (S17/K3) для эмиссии
                ``ai.invocation.*`` событий.
            cost_tracker: Cost-aggregator для bill / Langfuse OTel.
        """
        self._policy_resolver = policy_resolver
        self._capability_gate = capability_gate
        self._audit_service = audit_service
        self._cost_tracker = cost_tracker

    async def invoke(self, request: AIRequest) -> AIResponse:
        """Главный entrypoint AI-инвокации.

        Args:
            request: Запрос с ``workflow_id``, ``tenant_id``, ``correlation_id``,
                ``prompt_ref`` / ``prompt_inline``, ``context``, ``stream``.

        Returns:
            :class:`AIResponse` с финальным ``content`` + метаданными
            (tokens / cost / guards).

        Raises:
            CapabilityDeniedError: При ``enforce=True`` и отсутствии
                ``ai.invoke.<workflow_id>`` в plugin.toml::capabilities.
            PolicyNotResolvedError: При ``enforce=True`` и
                :data:`feature_flags.ai_policy_enforce = True`, если
                :class:`PolicyResolver` не нашёл подходящую policy с
                ``required=True``.

        Notes:
            При ``enforce=False`` (default scaffold-режим) делегирует
            в :meth:`_legacy_invoke` без enforcement.
        """
        from src.backend.core.config.features import feature_flags

        if not feature_flags.ai_gateway_enforce:
            return await self._legacy_invoke(request)
        return await self._enforced_invoke(request)

    async def _enforced_invoke(self, request: AIRequest) -> AIResponse:
        """Полный 9-step pipeline (impl S25 W1..W5 + S27 W2..W5).

        Args:
            request: AIRequest.

        Returns:
            AIResponse после прохождения всех 9 шагов.
        """
        policy = await self._resolve_policy(request)
        await self._check_capability(request)
        sanitized = await self._apply_input_sanitizers(request, policy)
        await self._apply_input_guards(sanitized, policy)
        rendered = await self._render_prompt(request, policy)
        completion = await self._invoke_llm(rendered, policy, request.stream)
        await self._apply_output_guards(completion, policy)
        sanitized_output = await self._apply_output_sanitizers(completion, policy)
        await self._audit_emit(request, policy, sanitized_output)
        await self._cost_track(request, policy, sanitized_output)
        return sanitized_output

    async def _legacy_invoke(self, request: AIRequest) -> AIResponse:
        """Pass-through до S27 closure: caller использует свой prompt напрямую.

        Используется только для backward-compat обёртки 3 кодопутей LLM.
        Возвращает пустой AIResponse — реальный вызов делает caller.

        Args:
            request: AIRequest (игнорируется в scaffold).

        Returns:
            Пустой AIResponse (placeholder, caller использует свой контракт).
        """
        return AIResponse(content="", model_used="pass-through-scaffold")

    async def _resolve_policy(self, request: AIRequest) -> "AIPolicySpec | None":
        """Шаг 1: PolicyResolver → AIPolicySpec.

        Args:
            request: AIRequest.

        Returns:
            Resolved AIPolicySpec; ``None`` если ``policy_resolver`` не задан.

        Raises:
            NotImplementedError: Полная реализация — Wave S25 W2.
        """
        if self._policy_resolver is None:
            return None
        raise NotImplementedError("S25 W2: PolicyResolver integration (ADR-NEW-20)")

    async def _check_capability(self, request: AIRequest) -> None:
        """Шаг 2: CapabilityGate intercept.

        Args:
            request: AIRequest.

        Raises:
            NotImplementedError: Wave S25 W1 closure (после AIGateway accept).
        """
        if self._capability_gate is None:
            return
        raise NotImplementedError("S25 W1: CapabilityGate intercept")

    async def _apply_input_sanitizers(
        self, request: AIRequest, policy: "AIPolicySpec | None"
    ) -> str:
        """Шаг 3: input sanitizers (PIITokenizer + Presidio).

        Args:
            request: AIRequest.
            policy: Resolved AIPolicySpec.

        Returns:
            Sanitized prompt string.

        Raises:
            NotImplementedError: Wave S25 W4 (PIITokenizer).
        """
        raise NotImplementedError("S25 W4: PIITokenizer integration (ADR-NEW-21)")

    async def _apply_input_guards(
        self, sanitized: str, policy: "AIPolicySpec | None"
    ) -> None:
        """Шаг 4: input guards (NeMo Colang + Rebuff/Lakera).

        Args:
            sanitized: Sanitized input после шага 3.
            policy: Resolved AIPolicySpec.

        Raises:
            NotImplementedError: Wave S24 W2 (NeMo+LlamaGuard) + S27 W2 (DSL).
        """
        raise NotImplementedError("S24 W2 + S27 W2: input guards (ADR-NEW-17)")

    async def _render_prompt(
        self, request: AIRequest, policy: "AIPolicySpec | None"
    ) -> str:
        """Шаг 5: PromptRenderer (Langfuse + tiktoken trim).

        Args:
            request: AIRequest.
            policy: Resolved AIPolicySpec (для budget).

        Returns:
            Rendered prompt после template + budget trim.

        Raises:
            NotImplementedError: Wave S26 W2 (prompt_render DSL processor).
        """
        raise NotImplementedError("S26 W2: prompt_render integration")

    async def _invoke_llm(
        self, rendered: str, policy: "AIPolicySpec | None", stream: bool
    ) -> AIResponse:
        """Шаг 6: ModelRouter (LiteLLM primary + fallback).

        Args:
            rendered: Готовый prompt.
            policy: Resolved AIPolicySpec (для ``model_router``).
            stream: Streaming flag.

        Returns:
            AIResponse с raw completion (до output guards/sanitize).

        Raises:
            NotImplementedError: Wave S25 W3 (Adapter wrap LiteLLM).
        """
        raise NotImplementedError("S25 W3: ModelRouter (LiteLLM facade)")

    async def _apply_output_guards(
        self, response: AIResponse, policy: "AIPolicySpec | None"
    ) -> None:
        """Шаг 7: output guards (Llama Guard 3).

        Args:
            response: Raw completion AIResponse.
            policy: Resolved AIPolicySpec.

        Raises:
            NotImplementedError: Wave S24 W2 + S27 W2.
        """
        raise NotImplementedError("S24 W2 + S27 W2: output guards (ADR-NEW-17)")

    async def _apply_output_sanitizers(
        self, response: AIResponse, policy: "AIPolicySpec | None"
    ) -> AIResponse:
        """Шаг 8: output sanitizers (Presidio + JSONSchema через Outlines).

        Args:
            response: Raw completion AIResponse.
            policy: Resolved AIPolicySpec.

        Returns:
            AIResponse с sanitized.content + structured (Pydantic).

        Raises:
            NotImplementedError: Wave S25 W4 + S26 W2.
        """
        raise NotImplementedError("S25 W4 + S26 W2: output sanitizers")

    async def _audit_emit(
        self,
        request: AIRequest,
        policy: "AIPolicySpec | None",
        response: AIResponse,
    ) -> None:
        """Шаг 9a: Audit emit (Unified AuditService → 9 событий ai.invocation.*).

        Args:
            request: AIRequest.
            policy: Resolved AIPolicySpec.
            response: Sanitized AIResponse.

        Raises:
            NotImplementedError: Wave S27 W5 (ADR-NEW-24 AI Audit Unified).
        """
        raise NotImplementedError("S27 W5: AI Audit Unified Schema (ADR-NEW-24)")

    async def _cost_track(
        self,
        request: AIRequest,
        policy: "AIPolicySpec | None",
        response: AIResponse,
    ) -> None:
        """Шаг 9b: Cost-tracker (Langfuse v3 OTel + Prometheus).

        Args:
            request: AIRequest.
            policy: Resolved AIPolicySpec (для budget enforce).
            response: AIResponse с tokens + cost_usd.

        Raises:
            NotImplementedError: Wave S25 W5 (Langfuse v3 OTel callback).
        """
        raise NotImplementedError("S25 W5: cost_tracker + Langfuse v3 OTel")
