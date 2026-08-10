"""Opt-in hybrid-adapter поверх :class:`AIGateway` (S25 W3, ADR-NEW-19).

Назначение
----------
Промежуточный слой для миграции существующих кодопутей LLM
(``services/ai/ai_agent.py``, ``services/ai/ai_graph.py``,
``services/ai/agents_pydantic/base.py``) на единую точку входа
:class:`core.ai.gateway.AIGateway` **без переписывания** этих модулей.

Принцип работы (hybrid):

* При :data:`feature_flags.ai_gateway_enforce = True` — конструируется
  :class:`AIRequest` из переданных параметров, вызывается
  :meth:`AIGateway.invoke`, возвращается ``response.content``.
* При :data:`feature_flags.ai_gateway_enforce = False` (default) —
  делегируется ``legacy_callable(*legacy_args, **legacy_kwargs)``;
  поведение полностью совпадает с pre-S25 W3 кодопутями.

Это позволяет постепенно мигрировать callers без single-cut breaking change:

* Шаг 1 (текущая wave) — adapter + tests. 3 LLM-модуля не модифицированы.
* Шаг 2 (carryover) — каждый из 3 LLM-модулей оборачивает свои публичные
  методы через :func:`invoke_via_gateway`.
* Шаг 3 (S27 closure) — flag ``ai_gateway_enforce`` → ``True`` в production;
  все callers идут через AIGateway, legacy-paths остаются как fallback.

Опасности
---------
* Adapter **не** подменяет публичный API существующих LLM-сервисов —
  caller сам решает, передавать ли результат как ``str`` (content) или
  как dict / Pydantic-объект. Несовместимость типов между legacy-result и
  ``AIResponse.content`` — ответственность caller'а.

См. также
---------
* :class:`core.ai.gateway.AIGateway` (ADR-NEW-19);
* :class:`core.ai.policy.spec.AIPolicySpec` (ADR-NEW-20);
* :mod:`tools.checks.check_ai_gateway_coverage` — AST-checker (S27 closure).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.core.ai import AIGateway, AIRequest

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

__all__ = (
    "AIGatewayAdapter",
    "adapt_capability_gate",
    "get_ai_gateway",
    "invoke_via_gateway",
)



def adapt_capability_gate(gate: Any) -> Any:
    """Адаптирует :class:`CapabilityGate` к 3-arg signature для AIGateway.

    Round 39: Sprint 1.5 L5 Security Chain — ``AIGateway._check_capability``
    вызывает ``gate.check(plugin, capability, requested_scope)``
    (canonical signature из :class:`CheckMixin.check`).

    Args:
        gate: :class:`CapabilityGate` instance с ``.check`` методом.

    Returns:
        Adapter object с тем же ``.check(plugin, capability, scope)`` interface
        (1-в-1 pass-through — canonical signal уже matches).

    Raises:
        CapabilityDeniedError: пробрасывается из gate без модификации.

    """
    return _CapabilityGateAdapter(gate)


class _CapabilityGateAdapter:
    """Round 39: thin pass-through adapter для canonical ``CheckMixin`` signature.

    Canonical ``gate.check(plugin, capability, requested_scope)`` уже matches
    AIGateway expectations. Этот adapter нужен только для testing contract
    (testability, mocking в :mod:`tests.unit.services.ai.test_aigateway_capability_wiring`).
    """

    __slots__ = ("_gate",)

    def __init__(self, gate: Any) -> None:
        self._gate = gate

    def check(self, plugin: str, capability: str, requested_scope: str | None) -> None:
        """Pass-through to canonical ``CheckMixin.check`` (3-arg signature)."""
        self._gate.check(plugin, capability, requested_scope)


def get_ai_gateway() -> AIGateway:
    """Получить singleton :class:`AIGateway` из composition root.

    Sprint 1 (Sprint 1.3 fix): проброс singleton-экземпляра AIGateway
    с обязательными DI (``policy_resolver``, ``capability_gate``,
    ``token_budget``) в кодопути ``services/ai/ai_graph.py``,
    ``dsl/workflow/compiler/activity_bridge.py`` и другие
    (4 callsites заменяют ``AIGateway()`` на ``get_ai_gateway()``).

    Composition-root приоритет: ``app.state.ai_gateway`` →
    :func:`src.backend.core.di.providers.ai.get_ai_gateway_provider`
    → fallback ``AIGateway()`` (dev only; production-wiring guard в
    :class:`AIGateway` бросает :class:`AIGatewayProductionWiringError`).

    Returns:
        :class:`AIGateway` с заполненными DI.

    """
    try:
        from src.backend.core.di.app_state import get_app_ref  # noqa: F401 — availability probe

        app = get_app_ref()
        if app is not None:
            gateway = getattr(app.state, "ai_gateway", None)
            if gateway is not None:
                return gateway
    except (ImportError, AttributeError, RuntimeError) as app_state_exc:
        # D-A1-04 fix (cycle 39): narrow exceptions + observability.
        # Bare `except Exception` маскировал broken app_state (early-init,
        # не инициализированный app.state). Fallback: provider chain.
        from src.backend.core.logging import get_logger  # noqa: F401 — availability probe
        get_logger(__name__).debug(
            "gateway_adapter.app_state_resolve_failed",
            extra={"error": str(app_state_exc)},
        )

    try:
        from src.backend.core.di.providers.ai import get_ai_gateway_provider

        return get_ai_gateway_provider()
    except (KeyError, RuntimeError) as exc:
        # cycle-1/B-05 fix: composition-root DI fail-closed. На production
        # отсутствие обязательных DI-параметров (policy_resolver /
        # capability_gate / token_budget) поднимает
        # AIGatewayProductionWiringError вместо silent bare AIGateway().
        try:
            from src.backend.core.ai.gateway import AIGatewayProductionWiringError  # noqa: F401 — availability probe

            from src.backend.core.logging import get_logger  # noqa: F401 — availability probe

            get_logger(__name__).error(
                "AIGateway: composition-root DI lookup failed",
                extra={
                    "component": "gateway_adapter",
                    "lookup": "get_ai_gateway_provider",
                },
            )
            raise AIGatewayProductionWiringError(
                missing=("ai_gateway",),
            ) from exc
        except ImportError:
            # Fallback когда production-guard недоступен (например в
            # unit-тестах без полной composition root): logger.error
            # остаётся, дальше — bare AIGateway() с явным признаком
            # failed DI lookup.
            from src.backend.core.logging import get_logger  # noqa: F401 — availability probe

            get_logger(__name__).error(
                "AIGateway: composition-root DI lookup failed; AIGatewayProductionWiringError unavailable",
                extra={
                    "component": "gateway_adapter",
                    "lookup": "get_ai_gateway_provider",
                },
            )
            return AIGateway()  # B-05 fix (cycle 1)


async def invoke_via_gateway(
    *,
    workflow_id: str,
    tenant_id: str,
    correlation_id: str,
    prompt: str,
    legacy_callable: Callable[..., Awaitable[Any]],
    legacy_args: tuple[Any, ...] = (),
    legacy_kwargs: dict[str, Any] | None = None,
    gateway: AIGateway | None = None,
    stream: bool = False,
    return_full_response: bool = False,
) -> Any:
    """Hybrid вызов: ``AIGateway.invoke`` при flag=ON или legacy_callable при OFF.

    Args:
        workflow_id: Идентификатор бизнес-операции (``"credit_check"``);
            используется :class:`PolicyResolver` для подбора
            :class:`AIPolicySpec`.
        tenant_id: Tenant из ``TenantContext`` для PII / quotas / SLO scope.
        correlation_id: Идентификатор запроса из :class:`RequestContext`
            (ADR-NEW-3) для аудит-trace.
        prompt: Inline-промпт (используется как ``AIRequest.prompt_inline``;
            Langfuse PromptRegistry — carryover Wave S26 W2).
        legacy_callable: Async-функция legacy-пути; вызывается при
            ``feature_flags.ai_gateway_enforce=False``. Сигнатура и
            возвращаемый тип определяются caller'ом.
        legacy_args: Позиционные аргументы для ``legacy_callable``.
        legacy_kwargs: Keyword-аргументы для ``legacy_callable``.
        gateway: Опциональная инстанция :class:`AIGateway`. При ``None``
            создаётся default (без injected dependencies — pipeline вернёт
            ``GatewayUnavailable`` если нет LiteLLM). Caller обычно
            инжектирует gateway через DI.
        stream: Передаётся в :class:`AIRequest.stream`; при ``True`` —
            streaming chunks (SSE/WebSocket).
        return_full_response: При ``True`` возвращает :class:`AIResponse`
            вместо ``str`` (для callers, которым нужны tokens/cost/model).

    Returns:
        При ``feature_flags.ai_gateway_enforce=True`` и
        ``return_full_response=False`` — :class:`str` (``AIResponse.content``).
        При ``return_full_response=True`` — :class:`AIResponse`.
        При ``False`` — результат ``legacy_callable(...)`` (тип определяет
        caller).

    Raises:
        ImportError: ``core.config.features`` недоступен (импорт-цикл при
            недокомплектованной установке).
        Любые исключения, поднятые ``legacy_callable`` или
        :meth:`AIGateway.invoke`.

    """
    from src.backend.core.config.features import feature_flags

    if not feature_flags.ai_gateway_enforce:
        return await legacy_callable(*legacy_args, **(legacy_kwargs or {}))

    gw = gateway if gateway is not None else get_ai_gateway()
    request = AIRequest(
        workflow_id=workflow_id,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        prompt_inline=prompt,
        stream=stream,
    )
    response = await gw.invoke(request)
    if return_full_response:
        return response
    return response.content


class AIGatewayAdapter:
    """Stateful версия :func:`invoke_via_gateway` для DI-инъекции.

    Caller инжектирует instance в свой сервис (например,
    :class:`AIAgentService`), затем вызывает :meth:`call` с legacy_callable.

    Пример::

        adapter = AIGatewayAdapter(gateway=AIGateway(policy_resolver=...))
        # внутри service-метода:
        result = await adapter.call(
            workflow_id="credit_check",
            tenant_id=request_context.tenant_id,
            correlation_id=request_context.correlation_id,
            prompt="...",
            legacy_callable=self._legacy_invoke_llm,
        )

    Args:
        gateway: :class:`AIGateway` instance с подключёнными зависимостями
            (policy_resolver / capability_gate / audit_service / ...).

    """

    def __init__(self, gateway: AIGateway) -> None:
        """Инициализация.

        Args:
            gateway: Инжектированный :class:`AIGateway` instance.

        """
        self._gateway = gateway

    async def call(
        self,
        *,
        workflow_id: str,
        tenant_id: str,
        correlation_id: str,
        prompt: str,
        legacy_callable: Callable[..., Awaitable[Any]],
        legacy_args: tuple[Any, ...] = (),
        legacy_kwargs: dict[str, Any] | None = None,
        stream: bool = False,
    ) -> Any:
        """Делегирует в :func:`invoke_via_gateway` с inj. gateway.

        Args:
            workflow_id: см. :func:`invoke_via_gateway`.
            tenant_id: см. :func:`invoke_via_gateway`.
            correlation_id: см. :func:`invoke_via_gateway`.
            prompt: см. :func:`invoke_via_gateway`.
            legacy_callable: см. :func:`invoke_via_gateway`.
            legacy_args: см. :func:`invoke_via_gateway`.
            legacy_kwargs: см. :func:`invoke_via_gateway`.
            stream: см. :func:`invoke_via_gateway`.

        Returns:
            См. :func:`invoke_via_gateway`.

        """
        return await invoke_via_gateway(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            prompt=prompt,
            legacy_callable=legacy_callable,
            legacy_args=legacy_args,
            legacy_kwargs=legacy_kwargs,
            gateway=self._gateway,
            stream=stream,
        )
