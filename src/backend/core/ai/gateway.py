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
from typing import TYPE_CHECKING, Any

from src.backend.core.ai.gateway_models import AIRequest, AIResponse
from src.backend.core.ai.gateway_orchestrator_mixin import EnforcedInvokeMixin
from src.backend.core.ai.gateway_pipeline_mixin import PipelineStepsMixin

if TYPE_CHECKING:
    from src.backend.core.ai.policy.spec import AIPolicySpec

__all__ = ("AIGateway", "AIRequest", "AIResponse")

logger = logging.getLogger(__name__)


class AIGateway(EnforcedInvokeMixin, PipelineStepsMixin):
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
    ) -> AIPolicySpec | None:
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

    # `_enforced_invoke` extracted в gateway_orchestrator_mixin.py (T-P1.1c)
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


# ── Mixins extracted (T-P1.1a/b/c):
#     _AuditContext, _emit_wrapper          → gateway_audit_mixin.py
#     _resolve_policy, _check_capability,   → gateway_pipeline_mixin.py
#     _apply_input_sanitizers, ... _cost_track
#     _enforced_invoke (9-step orchestrator) → gateway_orchestrator_mixin.py
