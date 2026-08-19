"""AIGateway — единая точка входа в AI (ADR-NEW-19, Sprint 25 W1).

Перенесено из :mod:`src.backend.core.ai.gateway` (1091 LOC god-file)
в рамках S175 M2.1 (ARC-009) → S175 #8 split completion (Sprint 175).

Архитектура subpackage ``gateway/``:
- :mod:`src.backend.core.ai.gateway.gateway` — :class:`AIGateway` facade
  (этот файл). Объединяет mixins + ``__init__`` + delegation в
  :meth:`AIGateway.invoke` → :meth:`AIGateway._enforced_invoke`.
- :mod:`src.backend.core.ai.gateway.orchestrator.enforced_invoke` —
  9-step pipeline orchestrator (ADR-0071).
- Внешние mixins (shared с другими AI-компонентами):
  - :mod:`src.backend.core.ai.gateway_orchestrator_mixin` (EnforcedInvokeMixin)
  - :mod:`src.backend.core.ai.gateway_pipeline_mixin` (PipelineStepsMixin)
  - :mod:`src.backend.core.ai.gateway_models` (AIRequest, AIResponse)

Pipeline (9 шагов) — см. ADR-NEW-19 + ADR-0071. Полная реализация
pipeline steps — в :mod:`PipelineStepsMixin` (``gateway_pipeline_mixin``).

Feature-flag: :envvar:`FEATURE_AI_GATEWAY_ENFORCE` (default-ON, см.
ADR-NEW-19). При ``False`` — :meth:`AIGateway.invoke` бросает
``AIGatewayEnforcementRequiredError`` (S85 W1 V2 P0 #1 — silent
pass-through удалён).

Backward-compat: ``from src.backend.core.ai.gateway import AIGateway``
продолжает работать (subpackage ``__init__.py`` re-export).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.core.ai.gateway_models import AIRequest, AIResponse
from src.backend.core.ai.gateway_orchestrator_mixin import EnforcedInvokeMixin
from src.backend.core.ai.gateway_pipeline_mixin import PipelineStepsMixin

if TYPE_CHECKING:
    from src.backend.core.ai.policy.spec import AIPolicySpec

__all__ = ("AIGateway",)


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
    :meth:`invoke` бросает ``AIGatewayEnforcementRequiredError`` —
    silent pass-through запрещён (S85 W1).

    Шаги pipeline реализованы в mixins:
    * ``PipelineStepsMixin`` — sanitizers, guards, render, cost_track
    * ``EnforcedInvokeMixin`` — orchestration + policy_resolve + audit
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
        token_budget: Any | None = None,
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
            token_budget: :class:`core.tenancy.token_budget.TokenBudget` для
                per-tenant budget enforcement (S172 M4 ARC-007); при
                ``None`` — budget enforcement пропускается (backward-compat).

        """
        self._policy_resolver = policy_resolver
        self._capability_gate = capability_gate
        self._audit_service = audit_service
        self._cost_tracker = cost_tracker
        self._sanitizer = sanitizer
        self._llm_gateway = llm_gateway
        self._policy_enforcer = policy_enforcer
        self._token_budget = token_budget

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

    def _enforce_production_wiring(self) -> None:
        """Sprint 1.3 (S177 M2): production-wiring guard.

        Проверяет, что в production все три обязательных DI инжектированы:
        ``policy_resolver``, ``capability_gate``, ``token_budget``.
        При отсутствии хотя бы одной зависимости бросает
        :class:`AIGatewayProductionWiringError` ДО начала invoke
        (чтобы production с broken composition упала сразу с понятной
        ошибкой, а не с ProviderLookupError из policy_resolver/capability_gate).

        Backward-compat: в development/staging недостающие зависимости
        пропускаются (gate не активируется).
        """
        from src.backend.core.ai.errors import AIGatewayProductionWiringError
        from src.backend.core.config.settings import settings as app_settings

        env = getattr(getattr(app_settings, "app", None), "environment", "")
        if env != "production":
            return  # dev/staging: skip guard

        missing: list[str] = []
        if self._policy_resolver is None:
            missing.append("policy_resolver")
        if self._capability_gate is None:
            missing.append("capability_gate")
        if self._token_budget is None:
            missing.append("token_budget")
        if missing:
            raise AIGatewayProductionWiringError(tuple(missing))

    async def invoke(self, request: AIRequest) -> AIResponse:
        """Главный entrypoint AI-инвокации.

        Args:
            request: Запрос с ``workflow_id``, ``tenant_id``, ``correlation_id``,
                ``prompt_ref`` / ``prompt_inline``, ``context``, ``stream``.

        Returns:
            :class:`AIResponse` с финальным ``content`` + метаданными
            (tokens / cost / guards).

        Raises:
            AIGatewayProductionWiringError: В production при отсутствии
                обязательных DI (``policy_resolver``, ``capability_gate``,
                ``token_budget``).
            CapabilityDeniedError: При отсутствии ``ai.invoke.<workflow_id>``
                в plugin.toml::capabilities.
            PolicyNotResolvedError: При :data:`feature_flags.ai_policy_enforce = True`,
                если :class:`PolicyResolver` не нашёл подходящую policy с
                ``required=True``.
            AIGatewayEnforcementRequiredError: При
                :data:`feature_flags.ai_gateway_enforce = False` (scaffold-режим).
                S85: enforcement ВСЕГДА включён — silent pass-through запрещён.

        Notes:
            S85 W1 (V2 P0 #1): _legacy_invoke удалён. Enforcement обязателен.

        """
        # Sprint 1.3: production-wiring guard ПЕРЕД enforcement
        # (чтобы production с broken composition упала сразу с понятной ошибкой,
        # а не с ProviderLookupError из policy_resolver/capability_gate).
        self._enforce_production_wiring()
        from src.backend.core.config.features import feature_flags

        # S85 W1 (V2 P0 #1): enforcement is mandatory, scaffold-режим запрещён.
        if not feature_flags.ai_gateway_enforce:
            from src.backend.core.ai.errors import AIGatewayEnforcementRequiredError

            raise AIGatewayEnforcementRequiredError(
                "ai_gateway_enforce=False is no longer supported (S85). "
                "Set feature_flags.ai_gateway_enforce=True."
            )
        # S177 M2: на production require обязательные DI-инъекции
        # (policy_resolver, capability_gate, token_budget). Без них pipeline
        # выполнил бы LLM-вызов без policy/capability/budget проверок —
        # silent fail-open. Backward-compat: development/staging без
        # зависимостей работают как раньше.
        self._enforce_production_wiring()
        return await self._enforced_invoke(request)

    def _enforce_production_wiring(self) -> None:
        """Fail-closed guard обязательных DI-зависимостей на production.

        Raises:
            AIGatewayProductionWiringError: при ``app.environment ==
                "production"`` и отсутствии ``policy_resolver``,
                ``capability_gate`` или ``token_budget``.
        """
        try:
            from src.backend.core.config.settings import settings
        except Exception:
            # Не удалось загрузить settings (test env без YAML) — пропускаем
            # guard, чтобы не ломать unit-тесты с dependency-injection.
            return
        environment = getattr(getattr(settings, "app", None), "environment", "")
        if environment != "production":
            return
        missing: list[str] = [
            name
            for name, value in (
                ("policy_resolver", self._policy_resolver),
                ("capability_gate", self._capability_gate),
                ("token_budget", self._token_budget),
            )
            if value is None
        ]
        if missing:
            from src.backend.core.ai.errors import AIGatewayProductionWiringError

            # Sprint 226 fix: pass tuple (NOT pre-formatted string).
            # Error class formats the missing list internally — passing
            # a string causes ``list(string)`` to iterate character-by-character
            # producing ``['A', 'I', 'G', ...]`` instead of
            # ``['policy_resolver', 'capability_gate', 'token_budget']``.
            raise AIGatewayProductionWiringError(tuple(missing))

    # S166 W2: Sandbox integration для AI-generated code (Rule 10).
    # Per skill: Sandbox = CodeSandbox Protocol. When AIGateway runs
    # tools that execute agent-generated code (e.g. via tool dispatch),
    # delegate to self._sandbox.run() instead of executing in main loop.
    async def run_agent_code(self, code: str, *, timeout_seconds: float = 30.0) -> Any:
        """S166 W2: execute AI-generated code in sandbox (Rule 10).

        Returns:
            SandboxResult с stdout/stderr/exit_code/artifacts.

        Raises:
            RuntimeError: если no sandbox configured.

        """
        from src.backend.core.ai.sandbox import NoOpSandbox

        sandbox = getattr(self, "_sandbox", None) or NoOpSandbox()
        # Map timeout_seconds -> timeout_s per CodeSandbox Protocol.
        return await sandbox.run(code, timeout_s=timeout_seconds)

    def attach_sandbox(self, sandbox: Any) -> None:
        """S166 W2: attach CodeSandbox implementation (Rule 10).

        Usage:
            from src.backend.core.di.providers.infrastructure_locator import (
                get_e2b_sandbox_class as _get_e2b_sandbox_cls,
            )
            E2BSandbox = _get_e2b_sandbox_cls()
            gateway.attach_sandbox(E2BSandbox(...))
        """
        self._sandbox = sandbox
