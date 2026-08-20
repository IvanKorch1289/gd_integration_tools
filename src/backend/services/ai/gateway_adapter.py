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

Sprint 1.5 (L5 Security Chain) — добавлен :func:`adapt_capability_gate` и
:func:`get_ai_gateway`. Canonical ``CapabilityGate`` ожидает сигнатуру
``(plugin, capability, scope)``, а AIGateway читает ``_capability_gate.check``
с теми же 3 аргументами. До Sprint 1.5 pipeline вызывал ``check(capability)``
с одним аргументом — :class:`TypeError` ловился silent ``except`` →
fail-open. Адаптер делает связь явной, и используется composition root'ом
для регистрации AIGateway в ``app.state.ai_gateway`` (см.
``setup_ai_stack.register_ai_stack_providers`` и
``plugins.composition.lifecycle.startup.run_startup``).

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

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from src.backend.core.ai import AIGateway, AIRequest
from src.backend.core.interfaces.capability_gateway import CapabilityGatewayProtocol

if TYPE_CHECKING:
    pass

__all__ = (
    "AIGatewayAdapter",
    "AdaptedCapabilityGate",
    "adapt_capability_gate",
    "get_ai_gateway",
    "invoke_via_gateway",
)


# NOTE: Sprint 7 audit — удалена shadowed duplicate ``adapt_capability_gate`` (line 72)
# которая была мертвым кодом (Python "last wins" — 2nd определение at line 214 always used).
# Класс ``_CapabilityGateAdapter`` оставлен для testability (используется в unit tests).


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


# NOTE: Sprint 7 audit — удалена shadowed duplicate ``get_ai_gateway``.
# Python "last wins" — actual behavior всегда uses 2nd определение (ниже, dev-fallback).
# Если нужен полный DI chain — используй ``src.backend.core.di.providers.ai.get_ai_gateway_provider``
# или ``src.backend.core.di.app_state.get_app_ref().state.ai_gateway``.


# NOTE: Sprint 7 audit — удалена shadowed duplicate ``get_ai_gateway`` (1st at line 94).
# Python "last wins" — actual behavior всегда uses 2nd определение (line ~209, dev-fallback).
# Если нужен полный DI chain — используй ``src.backend.core.di.providers.ai.get_ai_gateway_provider``
# или ``src.backend.core.di.app_state.get_app_ref().state.ai_gateway``.


CapabilityChecker = Callable[[str, str, str | None], None]


class AdaptedCapabilityGate:
    """Wrapper ``CapabilityGatewayProtocol`` для AIGateway (Sprint 1.5).

    AIGateway внутри читает ``self._capability_gate.check(...)`` через
    :func:`getattr`. Возвращаем объект с методом ``check``, который
    пробрасывает canonical 3-arg signature. Поведение fail-closed
    сохраняется: ``CapabilityDeniedError`` от gate пробрасывается дальше
    (см. :mod:`core.ai.gateway_pipeline_mixin.policy_mixin._check_capability`).
    """

    __slots__ = ("_gate",)

    def __init__(self, gate: CapabilityGatewayProtocol) -> None:
        """Инициализация.

        Args:
            gate: Capability gateway с трёхаргументным ``check``.
        """
        self._gate = gate

    def check(self, plugin: str, capability: str, scope: str | None) -> None:
        """Пробросить проверку без изменения fail-closed семантики gate."""
        self._gate.check(plugin, capability, scope)


def adapt_capability_gate(gate: CapabilityGatewayProtocol) -> CapabilityGatewayProtocol:
    """Адаптировать canonical ``CapabilityGate.check`` к AI-пайплайну.

    Args:
        gate: Capability gateway с трёхаргументным ``check``.

    Returns:
        Объект с методом ``.check(plugin, capability, scope)``,
        совместимый с :attr:`AIGateway._capability_gate`.
    """
    return AdaptedCapabilityGate(gate)


def get_ai_gateway() -> AIGateway:
    """Вернуть singleton AIGateway из composition root или dev-fallback.

    В production отсутствие регистрации не превращается в allow-all: созданный
    fallback остановится встроенным production-wiring guard при ``invoke``.
    """
    try:
        from src.backend.core.di.app_state import get_app_ref

        app = get_app_ref()
        if app is not None:
            gateway = getattr(app.state, "ai_gateway", None)
            if gateway is not None:
                return gateway
    except Exception as exc:
        # D-AUDIT-13501 fix (cycle 135): logger was undefined
        # (bare 'logger.debug' использовался без module-level import).
        # Inline import + get_logger(__name__) pattern matches
        # other usages в этом файле.
        from src.backend.core.logging import get_logger

        get_logger(__name__).debug("AIGateway app.state lookup skipped: %s", exc)

    try:
        from src.backend.core.di.providers.ai import get_ai_gateway_provider

        return get_ai_gateway_provider()
    except KeyError, RuntimeError:  # noqa: PIE801 — Python 3 tuple form (was X, Y syntax)
        return AIGateway()

CapabilityChecker = Callable[[str, str, str | None], None]



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
