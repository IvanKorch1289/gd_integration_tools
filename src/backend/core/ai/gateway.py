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
3. Input sanitizers (PIITokenizer из S25 W4 + Presidio из S24 W1).
4. Input guards (NeMo Colang из S24 W2 + Rebuff/Lakera).
5. ``PromptRenderer`` (Langfuse PromptRegistry + tiktoken budget trim).
6. ``ModelRouter`` (LiteLLM primary + fallback chain).
7. Output guards (Llama Guard 3 из S24 W2).
8. Output sanitizers (Presidio + JSONSchema через Outlines).
9. Audit + Cost (Unified AuditService из S17/K3 + Langfuse v3 OTel из S25 W5).

Feature-flag
------------
:envvar:`FEATURE_AI_GATEWAY_ENFORCE` (default-ON, см. ADR-NEW-19).

При ``False`` — :meth:`AIGateway.invoke` работает в **pass-through** режиме:
делегирует вызов в ``_legacy_invoke()`` без enforcement. Все 3 кодопути LLM
сохраняют существующий интерфейс (backward-compat).

При ``True`` (после S27 closure) — 100% LLM-вызовов через :class:`AIGateway`,
обходные пути блокируются ``check_ai_gateway_coverage`` AST-checker'ом.

Capability
----------
``ai.invoke.<workflow_id>`` — capability обязательна при ``enforce=True``;
регистрируется в :mod:`core.security.capabilities.vocabulary`.

9-event audit sequence
----------------------
После каждого шага pipeline эмитится событие ``ai.invocation.*`` через
:func:`emit_ai_invocation_event` (S27 W5 ADR-0071):

* ``requested`` — в начале _enforced_invoke
* ``policy_resolved`` — после _resolve_policy
* ``sanitized`` — после _apply_input_sanitizers
* ``guarded.input`` — после _apply_input_guards (с GuardResult)
* ``guarded.output`` — после _apply_output_guards (с GuardResult)
* ``completed`` / ``denied`` / ``failed`` — финальное событие по outcome

См. также
---------
* :class:`AIPolicySpec` — :mod:`core.ai.policy.spec` (ADR-NEW-20).
* :class:`PolicyResolver` — :mod:`core.ai.policy.resolver` (ADR-NEW-20).
* :class:`PIITokenizer` — :mod:`core.security.pii_tokenizer` (ADR-NEW-21).
* :class:`SkillRegistry` — :mod:`core.ai.skill_registry` (ADR-NEW-22).
* docs/adr/0066-ai-gateway-facade.md.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.backend.core.ai.errors import GuardResult
from src.backend.core.ai.gateway_audit_mixin import _AuditContext
from src.backend.core.ai.gateway_models import AIRequest, AIResponse
from src.backend.core.ai.gateway_pipeline_mixin import PipelineStepsMixin

if TYPE_CHECKING:
    from src.backend.core.ai.policy.spec import AIPolicySpec
    from src.backend.core.audit.schema.ai_invocation import AIInvocationEvent

__all__ = ("AIGateway", "AIRequest", "AIResponse")

logger = logging.getLogger(__name__)


class AIGateway(PipelineStepsMixin):
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

    Шаги pipeline (S25 W1 production cut)
    -------------------------------------
    * Шаги 1, 2 — реализованы scaffold-ом (policy resolve, capability gate).
    * Шаги 3, 8 — реализованы через :class:`PresidioSanitizerAdapter` (S24 W1).
    * Шаги 4, 7 — guards: при наличии Llama Guard в :class:`AIPolicyEnforcer`
      применяются, иначе no-op. Полная реализация — S24 W2.
    * Шаги 5, 6 — render + invoke_llm; в текущем cut'е используется
      ``prompt_inline`` (Langfuse PromptRegistry — Wave S26 W2) и
      :class:`LiteLLMGateway` напрямую (ModelRouter — Wave S25 W3).
    * Шаг 9 — audit через :class:`AuditService` (Unified — S17/K3).

    См. ADR-0066 раздел «DoD-критерии scaffold → Accepted».
    """

    def __init__(
        self,
        *,
        policy_resolver: Any | None = None,
        capability_gate: Any | None = None,
        audit_service: Any | None = None,
        cost_tracker: Any | None = None,
        sanitizer: Any | None = None,
        llm_gateway: Any | None = None,
        policy_enforcer: Any | None = None,
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
            sanitizer: Реализация ``AsyncPIISanitizerProtocol`` (например,
                :class:`PresidioSanitizerAdapter`); при ``None`` — резолвится
                через DI singleton.
            llm_gateway: :class:`LiteLLMGateway` для шага 6; при ``None``
                — резолвится через DI singleton.
            policy_enforcer: :class:`AIPolicyEnforcer` для guards (шаги
                4 и 7); при ``None`` — guards пропускаются (no-op).
        """
        self._policy_resolver = policy_resolver
        self._capability_gate = capability_gate
        self._audit_service = audit_service
        self._cost_tracker = cost_tracker
        self._sanitizer = sanitizer
        self._llm_gateway = llm_gateway
        self._policy_enforcer = policy_enforcer

    async def get_policy(
        self, workflow_id: str, tenant_id: str | None = None
    ) -> "AIPolicySpec | None":
        """Возвращает resolved :class:`AIPolicySpec` для заданного workflow.

        Позволяет extension developer узнать, какая модель будет использована,
        перед вызовом :meth:`invoke`.

        Usage::

            policy = await gateway.get_policy("credit_check", tenant_id="premium")
            if policy is not None:
                model = policy.model  # e.g., "openai/gpt-4o"
                await gateway.invoke(request)

        Args:
            workflow_id: Логический идентификатор бизнес-операции.
            tenant_id: Tenant identifier (опционально, для per-tenant override).

        Returns:
            Resolved :class:`AIPolicySpec` или ``None`` если resolver
            не нашёл подходящей политики.
        """
        if self._policy_resolver is None:
            return None
        return await self._policy_resolver.resolve(
            workflow_id=workflow_id, tenant_id=tenant_id
        )

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

        После каждого шага эмитит событие ``ai.invocation.*`` через
        :func:`emit_ai_invocation_event` (ADR-0071 §3):
        ``requested`` → ``policy_resolved`` → ``sanitized`` →
        ``guarded.input`` → ``guarded.output`` → ``completed|denied|failed``.

        Args:
            request: AIRequest.

        Returns:
            AIResponse после прохождения всех 9 шагов.
        """
        # Собираем контекст для аудита
        ctx = _AuditContext(request=request, audit_service=self._audit_service)
        start_ms = int(time.monotonic() * 1000)

        # Шаг 0: emit REQUESTED
        await ctx._emit("requested", latency_ms=int(time.monotonic() * 1000) - start_ms)

        # Шаг 1: policy resolution
        policy = await self._resolve_policy(request)
        ctx.policy = policy
        ctx.policy_name = policy.name if policy else "default"
        await ctx._emit(
            "policy_resolved", latency_ms=int(time.monotonic() * 1000) - start_ms
        )

        # Шаг 2: capability check (throws CapabilityDeniedError на fail)
        await self._check_capability(request)

        # Шаг 3: input sanitizers
        sanitized = await self._apply_input_sanitizers(request, policy)
        ctx.input_sanitized = sanitized
        ctx.input_pii_detected = getattr(self, "_last_input_pii_detected", False)
        await ctx._emit(
            "sanitized",
            pii_detected=ctx.input_pii_detected,
            latency_ms=int(time.monotonic() * 1000) - start_ms,
        )

        # Шаг 4: input guards
        input_guard_results = await self._apply_input_guards(sanitized, policy)
        ctx.input_guard_results = input_guard_results
        if input_guard_results:
            for gr in input_guard_results:
                await ctx._emit_guard("guarded.input", gr)
        else:
            await ctx._emit(
                "guarded.input", latency_ms=int(time.monotonic() * 1000) - start_ms
            )

        # Шаг 5: render prompt
        rendered = await self._render_prompt(request, policy, sanitized)
        ctx.rendered = rendered

        # Шаг 6: invoke LLM
        completion = await self._invoke_llm(rendered, policy, request.stream)
        ctx.completion = completion
        ctx.model_used = completion.model_used
        ctx.tokens_prompt = completion.tokens_prompt
        ctx.tokens_completion = completion.tokens_completion

        # Шаг 7: output guards
        output_guard_results = await self._apply_output_guards(completion, policy)
        ctx.output_guard_results = output_guard_results
        if output_guard_results:
            for gr in output_guard_results:
                await ctx._emit_guard("guarded.output", gr)
        else:
            await ctx._emit(
                "guarded.output", latency_ms=int(time.monotonic() * 1000) - start_ms
            )

        # Шаг 8: output sanitizers
        sanitized_output = await self._apply_output_sanitizers(completion, policy)

        # Шаг 9a: audit emit (завершающее событие)
        ctx.final_response = sanitized_output
        await ctx._emit_final(start_ms)

        # Шаг 9b: cost track
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
        del request
        return AIResponse(content="", model_used="pass-through-scaffold")


# ── _AuditContext, _emit_wrapper вынесены в gateway_audit_mixin (T-P1.1a) ────
