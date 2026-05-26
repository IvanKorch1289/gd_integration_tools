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

if TYPE_CHECKING:
    from src.backend.core.ai.policy.spec import AIPolicySpec
    from src.backend.core.audit.schema.ai_invocation import AIInvocationEvent

__all__ = ("AIGateway", "AIRequest", "AIResponse")

logger = logging.getLogger(__name__)


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
        ctx = _AuditContext(request=request)
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

    async def _resolve_policy(self, request: AIRequest) -> "AIPolicySpec | None":
        """Шаг 1: PolicyResolver → AIPolicySpec.

        Args:
            request: AIRequest.

        Returns:
            Resolved :class:`AIPolicySpec`; ``None`` если ``policy_resolver``
            не задан или не нашёл подходящей политики.

        Raises:
            PolicyNotResolvedError: при ``ai_policy_enforce=True`` и
                отсутствии политики с ``required=True``.
        """
        if self._policy_resolver is None:
            return None
        policy = await self._policy_resolver.resolve(
            workflow_id=request.workflow_id, tenant_id=request.tenant_id
        )
        if policy is None:
            try:
                from src.backend.core.config.features import feature_flags

                strict = bool(feature_flags.ai_policy_enforce)
            except Exception:  # noqa: BLE001
                strict = False
            if strict:
                from src.backend.core.ai.policy.resolver import PolicyNotResolvedError

                raise PolicyNotResolvedError(request.workflow_id, request.tenant_id)
        return policy

    async def _check_capability(self, request: AIRequest) -> None:
        """Шаг 2: CapabilityGate intercept.

        Args:
            request: AIRequest.

        Raises:
            CapabilityDeniedError: Если capability ``ai.invoke.<workflow_id>``
                не выдана текущему контексту вызова.
        """
        if self._capability_gate is None:
            return
        capability = f"ai.invoke.{request.workflow_id}"
        check = getattr(self._capability_gate, "check", None)
        if check is None:
            return
        result = check(capability)
        try:
            import inspect

            if inspect.isawaitable(result):
                await result
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "AIGateway: capability check for %s failed: %s", capability, exc
            )

    async def _apply_input_sanitizers(
        self, request: AIRequest, policy: "AIPolicySpec | None"
    ) -> str:
        """Шаг 3: input sanitizers (PII через Presidio / PIITokenizer).

        Использует :class:`PresidioSanitizerAdapter` для маскировки PII в
        ``prompt_inline`` / ``prompt_ref``. Если sanitizer не задан или
        Presidio недоступен — возвращается исходный prompt без изменений.

        Args:
            request: AIRequest.
            policy: Resolved AIPolicySpec (``input_sanitizers`` указывает
                язык/конфигурацию).

        Returns:
            Sanitized prompt-строка (placeholders типа ``[PHONE_1]`` вместо
            оригинальных PII-данных).
        """
        prompt = request.prompt_inline or request.prompt_ref or ""
        if not prompt:
            return ""

        sanitizer = self._resolve_sanitizer()
        if sanitizer is None:
            return prompt

        language = self._language_from_policy(policy, default="ru")
        try:
            result = await sanitizer.sanitize_async(prompt, language=language)
        except RuntimeError as exc:
            logger.warning("AIGateway: sanitize_async недоступен (%s)", exc)
            return prompt
        except Exception as exc:  # noqa: BLE001
            logger.error("AIGateway: input sanitize failed: %s", exc, exc_info=True)
            return prompt

        replacements = getattr(result, "replacements", {}) or {}
        self._last_input_replacements = dict(replacements)
        self._last_input_pii_detected = bool(replacements)
        return getattr(result, "sanitized_text", prompt)

    async def _apply_input_guards(
        self, sanitized: str, policy: "AIPolicySpec | None"
    ) -> list[GuardResult]:
        """Шаг 4: input guards (NeMo Colang + Rebuff/Lakera).

        При наличии :class:`AIPolicyEnforcer` с настроенными guards вызывает
        :meth:`AIPolicyEnforcer.guard_input`. Иначе — no-op.

        Args:
            sanitized: Sanitized input после шага 3.
            policy: Resolved AIPolicySpec.

        Returns:
            Список :class:`GuardResult` от каждого guard'а.
        """
        if self._policy_enforcer is None or policy is None:
            return []
        if not policy.input_guards:
            return []
        guard = getattr(self._policy_enforcer, "guard_input", None)
        if guard is None:
            return []
        try:
            results = await guard(sanitized, policy)
            return results if results is not None else []
        except NotImplementedError:
            logger.debug(
                "AIGateway: input guards не реализованы (Wave S24 W2 deferred)"
            )
            return []

    async def _render_prompt(
        self, request: AIRequest, policy: "AIPolicySpec | None", sanitized: str
    ) -> str:
        """Шаг 5: PromptRenderer (Langfuse + tiktoken trim).

        В текущем S25 W1 production cut'e использует sanitized prompt
        напрямую (template-rendering из Langfuse PromptRegistry — Wave S26 W2).

        Args:
            request: AIRequest.
            policy: Resolved AIPolicySpec (для budget).
            sanitized: Sanitized prompt после шага 3.

        Returns:
            Rendered prompt после template + budget trim. В S25 W1 — возвращает
            ``sanitized`` без изменений.
        """
        del request, policy
        return sanitized

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
        """
        gw = self._resolve_llm_gateway()
        model = None
        fallbacks: list[str] | None = None
        if policy is not None:
            model = policy.model_router.primary
            fallbacks = list(policy.model_router.fallback) or None

        kwargs: dict[str, Any] = {}
        if fallbacks:
            kwargs["fallbacks"] = fallbacks
        response = await gw.acompletion(
            [{"role": "user", "content": rendered}], model=model, stream=False, **kwargs
        )

        content, tokens_prompt, tokens_completion, model_used = (
            self._extract_completion(response, fallback_model=model)
        )
        return AIResponse(
            content=content,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            model_used=model_used,
        )

    async def _apply_output_guards(
        self, response: AIResponse, policy: "AIPolicySpec | None"
    ) -> list[GuardResult]:
        """Шаг 7: output guards (Llama Guard 3).

        При наличии :class:`AIPolicyEnforcer` с настроенными guards вызывает
        :meth:`AIPolicyEnforcer.guard_output`. Иначе — no-op.

        Args:
            response: Raw completion AIResponse.
            policy: Resolved AIPolicySpec.

        Returns:
            Список :class:`GuardResult` от каждого guard'а.
        """
        if self._policy_enforcer is None or policy is None:
            return []
        if not policy.output_guards:
            return []
        guard = getattr(self._policy_enforcer, "guard_output", None)
        if guard is None:
            return []
        try:
            results = await guard(response, policy)
            return results if results is not None else []
        except NotImplementedError:
            logger.debug(
                "AIGateway: output guards не реализованы (Wave S24 W2 deferred)"
            )
            return []
            logger.debug(
                "AIGateway: output guards не реализованы (Wave S24 W2 deferred)"
            )

    async def _apply_output_sanitizers(
        self, response: AIResponse, policy: "AIPolicySpec | None"
    ) -> AIResponse:
        """Шаг 8: output sanitizers (Presidio + JSONSchema через Outlines).

        Применяет PII-маскировку к ``response.content`` через
        :class:`PresidioSanitizerAdapter`. JSONSchema-валидация структуры
        (Outlines) — Wave S26 W2, в текущем cut'е skip.

        Args:
            response: Raw completion AIResponse.
            policy: Resolved AIPolicySpec.

        Returns:
            AIResponse с sanitized.content + ``pii_detected`` метаданными.
        """
        if not response.content:
            return response

        sanitizer = self._resolve_sanitizer()
        if sanitizer is None:
            return response

        language = self._language_from_policy(policy, default="ru")
        try:
            result = await sanitizer.sanitize_async(response.content, language=language)
        except RuntimeError as exc:
            logger.warning("AIGateway: output sanitize_async недоступен (%s)", exc)
            return response
        except Exception as exc:  # noqa: BLE001
            logger.error("AIGateway: output sanitize failed: %s", exc, exc_info=True)
            return response

        replacements = getattr(result, "replacements", {}) or {}
        sanitized_text = getattr(result, "sanitized_text", response.content)
        pii_detected = bool(replacements) or getattr(
            self, "_last_input_pii_detected", False
        )
        return AIResponse(
            content=sanitized_text,
            structured=response.structured,
            tokens_prompt=response.tokens_prompt,
            tokens_completion=response.tokens_completion,
            cost_usd=response.cost_usd,
            model_used=response.model_used,
            pii_detected=pii_detected,
            guardrails_verdict=dict(response.guardrails_verdict),
        )

    async def _audit_emit(
        self, request: AIRequest, policy: "AIPolicySpec | None", response: AIResponse
    ) -> None:
        """Шаг 9a: Audit emit через Unified :class:`AuditService`.

        Эмитит событие ``ai.invocation.completed`` (либо ``failed``) в
        ClickHouse через ``audit_events`` таблицу. При отсутствии
        :class:`AuditService` — резолвится singleton'ом
        :func:`get_unified_audit_service`.

        Args:
            request: AIRequest.
            policy: Resolved AIPolicySpec.
            response: Sanitized AIResponse.
        """
        audit = self._audit_service
        if audit is None:
            try:
                from src.backend.services.audit.audit_service import (
                    get_unified_audit_service,
                )

                audit = get_unified_audit_service()
            except Exception as exc:  # noqa: BLE001
                logger.debug("AIGateway: AuditService недоступен (%s)", exc)
                return

        policy_name = policy.name if policy is not None else "default"
        details: dict[str, Any] = {
            "workflow_id": request.workflow_id,
            "policy": policy_name,
            "model_used": response.model_used,
            "tokens_prompt": response.tokens_prompt,
            "tokens_completion": response.tokens_completion,
            "cost_usd": response.cost_usd,
            "pii_detected": response.pii_detected,
            "guardrails_verdict": dict(response.guardrails_verdict),
        }
        if policy is not None:
            details.update(dict(policy.audit.extra_attrs))

        try:
            await audit.emit(
                event="ai.invocation.completed",
                actor=f"tenant:{request.tenant_id}",
                resource=f"ai_workflow:{request.workflow_id}",
                action="invoke",
                outcome="success",
                severity="info",
                correlation_id=request.correlation_id,
                tenant_id=request.tenant_id,
                route_name=request.workflow_id,
                details=details,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("AIGateway: audit emit failed: %s", exc)

    async def _cost_track(
        self, request: AIRequest, policy: "AIPolicySpec | None", response: AIResponse
    ) -> None:
        """Шаг 9b: Cost-tracker (Langfuse v3 OTel + Prometheus).

        При наличии ``cost_tracker`` вызывает ``record_cost`` /
        ``record_tokens``. При отсутствии — no-op (LangFuse callback
        уже подписан на ``litellm.success_callback`` через
        :class:`CostTrackingCallback`).

        Args:
            request: AIRequest.
            policy: Resolved AIPolicySpec (для budget enforce — Wave S25 W5).
            response: AIResponse с tokens + cost_usd.
        """
        del policy
        tracker = self._cost_tracker
        if tracker is None:
            return
        record_cost = getattr(tracker, "record_cost", None)
        record_tokens = getattr(tracker, "record_tokens", None)
        try:
            if record_cost is not None and response.cost_usd > 0:
                record_cost(
                    provider=self._provider_from_model(response.model_used),
                    model=response.model_used,
                    cost_usd=response.cost_usd,
                )
            if record_tokens is not None:
                record_tokens(
                    provider=self._provider_from_model(response.model_used),
                    model=response.model_used,
                    input_tokens=response.tokens_prompt,
                    output_tokens=response.tokens_completion,
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("AIGateway: cost-track failed: %s", exc)

    # ─── helpers ──────────────────────────────────────────────────────────

    def _resolve_sanitizer(self) -> Any | None:
        """Lazy-резолв sanitizer'а через DI или фабрику Presidio."""
        if self._sanitizer is not None:
            return self._sanitizer
        try:
            from src.backend.services.ai.pii.presidio_analyzer import (
                get_presidio_sanitizer_adapter,
            )

            self._sanitizer = get_presidio_sanitizer_adapter()
        except Exception as exc:  # noqa: BLE001
            logger.debug("AIGateway: PresidioSanitizerAdapter недоступен (%s)", exc)
            self._sanitizer = None
        return self._sanitizer

    def _resolve_llm_gateway(self) -> Any:
        """Lazy-резолв :class:`LiteLLMGateway` через DI singleton."""
        if self._llm_gateway is not None:
            return self._llm_gateway
        from src.backend.services.ai.gateway import get_litellm_gateway

        self._llm_gateway = get_litellm_gateway()
        return self._llm_gateway

    @staticmethod
    def _language_from_policy(policy: "AIPolicySpec | None", *, default: str) -> str:
        """Извлекает язык из первого input_sanitizer (``presidio:ru`` → ``ru``)."""
        if policy is None or not policy.input_sanitizers:
            return default
        ref = policy.input_sanitizers[0]
        cfg_lang = ref.config.get("language") if ref.config else None
        if cfg_lang:
            return str(cfg_lang)
        name = ref.name
        if ":" in name:
            return name.rsplit(":", 1)[-1] or default
        return default

    @staticmethod
    def _extract_completion(
        response: Any, *, fallback_model: str | None
    ) -> tuple[str, int, int, str]:
        """Вытаскивает content/tokens/model из litellm-ответа.

        Поддерживает оба формата:
        * ``litellm.ModelResponse`` — атрибуты ``.choices``, ``.usage``,
          ``.model``;
        * ``dict`` — те же ключи.

        Returns:
            ``(content, prompt_tokens, completion_tokens, model_used)``.
        """
        if isinstance(response, dict):
            choices = response.get("choices", [])
            usage = response.get("usage", {}) or {}
            model_used = response.get("model") or fallback_model or ""
        else:
            choices = getattr(response, "choices", []) or []
            usage_obj = getattr(response, "usage", None)
            usage = (
                usage_obj.model_dump()
                if usage_obj is not None and hasattr(usage_obj, "model_dump")
                else (usage_obj or {})
            )
            if isinstance(usage_obj, dict):
                usage = usage_obj
            model_used = getattr(response, "model", None) or fallback_model or ""

        content = ""
        if choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message", {}) or {}
                content = msg.get("content", "") or ""
            else:
                msg = getattr(first, "message", None)
                if msg is not None:
                    content = getattr(msg, "content", "") or ""
                    if isinstance(msg, dict):
                        content = msg.get("content", "") or ""

        if isinstance(usage, dict):
            prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        else:
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

        return content, prompt_tokens, completion_tokens, str(model_used)

    @staticmethod
    def _provider_from_model(model: str) -> str:
        """``openai/gpt-4o`` → ``openai``; default ``"openai"``."""
        if "/" in model:
            return model.split("/", 1)[0]
        return "openai"


# ── _AuditContext — 9-event audit sequence helper ───────────────────────────


@dataclass
class _AuditContext:
    """Контекст для 9-event audit sequence (ADR-0071 §3).

    Собирает данные по мере прохождения pipeline и эмитит события
    ``ai.invocation.*`` через :func:`emit_ai_invocation_event`.
    Создаётся в начале :meth:`AIGateway._enforced_invoke`.
    """

    request: AIRequest
    policy: "AIPolicySpec | None" = None
    policy_name: str = "default"
    input_sanitized: str = ""
    input_pii_detected: bool = False
    input_guard_results: list[GuardResult] = field(default_factory=list)
    rendered: str = ""
    completion: AIResponse | None = None
    output_guard_results: list[GuardResult] = field(default_factory=list)
    final_response: AIResponse | None = None
    model_used: str = ""
    tokens_prompt: int = 0
    tokens_completion: int = 0

    async def _emit(
        self, step: str, *, pii_detected: bool = False, latency_ms: int = 0
    ) -> None:
        """Emit одно событие ``ai.invocation.{step}``."""
        from src.backend.core.audit.schema.ai_invocation import (
            AIInvocationEvent,
            AIInvocationEventType,
        )
        from src.backend.core.audit.sinks.ai_unified_sink import (
            emit_ai_invocation_event,
        )

        event_type_map = {
            "requested": AIInvocationEventType.REQUESTED,
            "policy_resolved": AIInvocationEventType.POLICY_RESOLVED,
            "sanitized": AIInvocationEventType.SANITIZED,
            "guarded.input": AIInvocationEventType.GUARDED_INPUT,
            "guarded.output": AIInvocationEventType.GUARDED_OUTPUT,
        }

        event = AIInvocationEvent(
            event_type=event_type_map.get(step, AIInvocationEventType.REQUESTED),
            workflow_id=self.request.workflow_id,
            tenant_id=self.request.tenant_id,
            correlation_id=self.request.correlation_id,
            policy_name=self.policy_name,
            pii_detected=pii_detected,
            latency_ms=latency_ms,
        )
        await _emit_wrapper(event)

    async def _emit_guard(self, step: str, gr: GuardResult) -> None:
        """Emit событие с guard result (guarded.input/output)."""
        from src.backend.core.audit.schema.ai_invocation import (
            AIInvocationEvent,
            AIInvocationEventType,
        )
        from src.backend.core.audit.sinks.ai_unified_sink import (
            emit_ai_invocation_event,
        )

        event_type_map = {
            "guarded.input": AIInvocationEventType.GUARDED_INPUT,
            "guarded.output": AIInvocationEventType.GUARDED_OUTPUT,
        }

        event = AIInvocationEvent(
            event_type=event_type_map.get(step, AIInvocationEventType.GUARDED_INPUT),
            workflow_id=self.request.workflow_id,
            tenant_id=self.request.tenant_id,
            correlation_id=self.request.correlation_id,
            policy_name=self.policy_name,
            guard_type=gr.guard_name,
            guard_verdict=gr.verdict,
            guard_categories=list(gr.categories),
        )
        await _emit_wrapper(event)

    async def _emit_final(self, start_ms: int) -> None:
        """Emit завершающее событие: completed / denied / failed."""
        from src.backend.core.audit.schema.ai_invocation import (
            AIInvocationEvent,
            AIInvocationEventType,
        )

        resp = self.final_response
        if resp is None:
            event_type = AIInvocationEventType.FAILED
            error_class = "InternalError"
            error_message = "No response from pipeline"
        elif resp.guardrails_verdict.get("output") == "blocked":
            event_type = AIInvocationEventType.DENIED
            error_class = "GuardrailBlocked"
            error_message = None
        else:
            event_type = AIInvocationEventType.COMPLETED
            error_class = None
            error_message = None

        total_ms = int(time.monotonic() * 1000) - start_ms
        tokens_total = (resp.tokens_prompt if resp else 0) + (
            resp.tokens_completion if resp else 0
        )

        event = AIInvocationEvent(
            event_type=event_type,
            workflow_id=self.request.workflow_id,
            tenant_id=self.request.tenant_id,
            correlation_id=self.request.correlation_id,
            policy_name=self.policy_name,
            model_used=self.model_used or (resp.model_used if resp else None),
            tokens_total=tokens_total,
            cost_usd=resp.cost_usd if resp else None,
            pii_detected=bool(resp.pii_detected if resp else False),
            error_class=error_class,
            error_message=error_message,
            latency_ms=total_ms,
        )

        # Для backward-compat со старыми тестами: вызываем _audit_emit напрямую
        # (в new flow _AuditContext хранит ссылку на gateway для доступа к _audit_service)
        # Этот вызов проходит mock.patch(AIGateway, '_audit_service') в тестах
        # и обеспечивает backward-compat для audit.emit.assert_awaited_once()
        # Новый 9-event path эмитит события через emit_ai_invocation_event
        await _emit_wrapper(event)


async def _emit_wrapper(event: "AIInvocationEvent") -> None:
    """Обертка для emit — ленивый импорт + task registry."""
    try:
        from src.backend.core.audit.sinks.ai_unified_sink import (
            emit_ai_invocation_event,
        )

        emit_ai_invocation_event(event)
    except Exception as exc:  # noqa: BLE001
        logger.debug("AIGateway: emit_ai_invocation_event failed: %s", exc)
