"""Structural category index for RouteBuilder MRO composition (2026-08-14).

## Зачем

Pre-2026-08-14: ``RouteBuilder`` (god-class антипаттерн) имел **36
top-level mixin-классов** в едином MRO и **~400+ публичных методов**
на instance (см. ``is_runtime_protocol_conformant`` тест в
``tests/unit/dsl/builders/test_protocols.py`` — все 8 категорий
конформны на реальном ``RouteBuilder()``).
Mixins разбросаны по ``src/backend/dsl/builders/``, ``src/backend/dsl/builders/base/``
и ``src/backend/dsl/processors/``. Новые фичи добавлялись в произвольный mixin без
документации о том, к какой функциональной категории builder'а они относятся.

Этот файл — каталог: **mixin → 8 категорий**. Если хотите добавить новую
фичу в правильное место — откройте ``_CATEGORY_MAP`` ниже и найдите
соответствующую категорию + mixin. MRO ``RouteBuilder`` остаётся
**неизменным** (см. ``base/__init__.py:102-139``).

## 8 категорий

1. **ControlFlow** — Choice, Saga, Retry, loop, fork-join, defer
2. **EIP** — Enterprise Integration Patterns: routing, channels,
   transformers, templates
3. **DataStore** — table-level + step-level + collection operations
4. **Transport** — SSE/CDC/MQ/HTTP source builders (``from_*``)
5. **Infrastructure** — fluent chain, config, validation, DI,
   feature flags, infrastructure DSL primitives
6. **Resilience** — circuit-breaker, bulkhead, compliance, middleware,
   IP restriction, route-level policy
7. **AIAgent** — AI/RPA, agent loop, plan-execute, reflection,
   router-specialist, notebook execution
8. **Messaging** — event-bus pub/sub, integration orchestration,
   route variables

## Использование

Через ``get_category_for_mixin("EIPMixin")`` — узнать категорию миксина.
Через ``get_protocol_for_category("EIP")`` — получить category-level Protocol.
``is_runtime_protocol_conformant(route_builder, "EIP")`` — проверить
наличие всех миксинов этой категории в MRO instance (для диагностики).

## Статус

Это **документационный index**, а не runtime-checkable contract.
В отличие от типичного ``Protocol``, здесь нет деклараций методов —
RouteBuilder имеет ~400+ публичных методов, и охватить их в одной
Protocol-декларации было бы шумом и источником ошибок. Вместо этого —
категории + mixin-mapping + ссылка на source-файл mixin'а для подробностей.
"""

from __future__ import annotations as annotations

from typing import TYPE_CHECKING as TYPE_CHECKING
from typing import Any as Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder


# ─── 8 Protocol-классов (категории) ───


class ControlFlowProtocol:
    """Choice, Saga, Retry, loop, fork-join, defer.

    Mixins: ``ControlFlowMixin``, ``SagaLRAMixin``, ``BatchMixin``,
    ``DeferredExecutionMixin``, ``PlanExecuteMixin``, ``ReflectionLoopMixin``.

    Source files:
    - ``src/backend/dsl/builders/control_flow.py``
    - ``src/backend/dsl/builders/saga_lra.py``
    - ``src/backend/dsl/builders/batch.py``
    - ``src/backend/dsl/builders/deferred_execution_mixin.py``
    - ``src/backend/dsl/processors/plan_execute_processor.py``
    - ``src/backend/dsl/processors/reflection_loop_processor.py``
    """


class EIPProtocol:
    """Enterprise Integration Patterns: routing, channels, transformers, templates.

    Mixins: ``EIPMixin``, ``EIPContentMixin``, ``ContentMixin``,
    ``ConvertersMixin``, ``FormatConvertersMixin``, ``RequestReplyMixin``,
    ``TemplateEngineMixin``, ``TemplateEngineChainMixin``.

    Source files:
    - ``src/backend/dsl/builders/eip.py``
    - ``src/backend/dsl/builders/content.py``
    - ``src/backend/dsl/builders/content_mixin.py``
    - ``src/backend/dsl/builders/converters.py``
    - ``src/backend/dsl/builders/converters_mixin.py``
    - ``src/backend/dsl/builders/request_reply.py``
    - ``src/backend/dsl/builders/template_engine.py``
    - ``src/backend/dsl/builders/template_engine_mixin.py``
    """


class DataStoreProtocol:
    """Table-level + step-level + collection operations.

    Mixins: ``DataStoreMixin``, ``DataStoreStepMixin``, ``CollectionMixin``.

    Source files:
    - ``src/backend/dsl/builders/data_store.py``
    - ``src/backend/dsl/builders/data_store_mixin.py``
    - ``src/backend/dsl/builders/collection.py``
    """


class TransportProtocol:
    """SSE/CDC/MQ/HTTP source builders (``from_*``).

    Mixin: ``TransportSourcesMixin`` (он же ``SourcesMixin`` в MRO — alias).

    Source files:
    - ``src/backend/dsl/builders/sources_mixin.py``
    """


class InfrastructureProtocol:
    """Fluent chain, config, validation, DI, feature flags, infrastructure DSL.

    Mixins: ``InfrastructureDSL``, ``FluentMixin``, ``ConfigMixin``,
    ``ValidationMixin``, ``DepsMixin``, ``FeatureMixin``.

    Source files:
    - ``src/backend/dsl/builders/infrastructure_dsl.py``
    - ``src/backend/dsl/builders/base/fluent_mixin.py``
    - ``src/backend/dsl/builders/base/config_mixin.py``
    - ``src/backend/dsl/builders/base/validation_mixin.py``
    - ``src/backend/dsl/builders/base/deps_mixin.py``
    - ``src/backend/dsl/builders/base/feature_mixin.py``
    """


class ResilienceProtocol:
    """Cross-cutting: circuit-breaker, bulkhead, compliance, middleware, IP, policy.

    Mixins: ``ResilienceMixin``, ``ComplianceMixin``, ``MiddlewareMixin``,
    ``IPRestrictionMixin``, ``PolicyMixin``.

    Source files:
    - ``src/backend/dsl/builders/base/resilience_mixin.py``
    - ``src/backend/dsl/builders/base/compliance_mixin.py``
    - ``src/backend/dsl/builders/base/middleware_mixin.py``
    - ``src/backend/dsl/builders/ip_restriction_mixin.py``
    - ``src/backend/dsl/builders/policy_mixin.py``
    """


class AIAgentProtocol:
    """AI/RPA, agent loop, plan-execute, reflection, router-specialist, notebook.

    Mixins: ``AIRPAMixin``, ``AgentDSLMixin``, ``RouterSpecialistMixin``,
    ``NotebookMixin`` + ``PlanExecuteMixin`` + ``ReflectionLoopMixin``
    (последние две относятся одновременно к ControlFlow и AI).

    Source files:
    - ``src/backend/dsl/builders/ai_rpa.py``
    - ``src/backend/dsl/builders/agent_dsl.py``
    - ``src/backend/dsl/processors/router_specialist_processor.py``
    - ``src/backend/dsl/builders/notebook.py``
    - ``src/backend/dsl/processors/plan_execute_processor.py``
    - ``src/backend/dsl/processors/reflection_loop_processor.py``
    """


class MessagingProtocol:
    """Event-bus pub/sub, integration orchestration, route variables.

    Mixins: ``EventBusMixin``, ``IntegrationMixin``, ``VariableMixin``.

    Source files:
    - ``src/backend/dsl/builders/eventbus_mixin.py``
    - ``src/backend/dsl/builders/integration.py``
    - ``src/backend/dsl/builders/variable_mixin.py``
    """


# ─── Mixin → category mapping ───


_CATEGORY_MAP: dict[str, type] = {
    # ControlFlow
    "ControlFlowMixin": ControlFlowProtocol,
    "SagaLRAMixin": ControlFlowProtocol,
    "BatchMixin": ControlFlowProtocol,
    "DeferredExecutionMixin": ControlFlowProtocol,
    "PlanExecuteMixin": AIAgentProtocol,  # also control-flow; primary = AI
    "ReflectionLoopMixin": AIAgentProtocol,  # also control-flow; primary = AI
    # EIP
    "EIPMixin": EIPProtocol,
    "EIPContentMixin": EIPProtocol,
    "ContentMixin": EIPProtocol,
    "ConvertersMixin": EIPProtocol,
    "FormatConvertersMixin": EIPProtocol,
    "RequestReplyMixin": EIPProtocol,
    "TemplateEngineMixin": EIPProtocol,
    "TemplateEngineChainMixin": EIPProtocol,
    # DataStore
    "DataStoreMixin": DataStoreProtocol,
    "DataStoreStepMixin": DataStoreProtocol,
    "CollectionMixin": DataStoreProtocol,
    # Transport
    "TransportSourcesMixin": TransportProtocol,
    # Infrastructure
    "InfrastructureDSL": InfrastructureProtocol,
    "FluentMixin": InfrastructureProtocol,
    "ConfigMixin": InfrastructureProtocol,
    "ValidationMixin": InfrastructureProtocol,
    "DepsMixin": InfrastructureProtocol,
    "FeatureMixin": InfrastructureProtocol,
    # Resilience
    "ResilienceMixin": ResilienceProtocol,
    "ComplianceMixin": ResilienceProtocol,
    "MiddlewareMixin": ResilienceProtocol,
    "IPRestrictionMixin": ResilienceProtocol,
    "PolicyMixin": ResilienceProtocol,
    # AIAgent
    "AIRPAMixin": AIAgentProtocol,
    "AgentDSLMixin": AIAgentProtocol,
    "RouterSpecialistMixin": AIAgentProtocol,
    "NotebookMixin": AIAgentProtocol,
    # Messaging
    "EventBusMixin": MessagingProtocol,
    "IntegrationMixin": MessagingProtocol,
    "VariableMixin": MessagingProtocol,
}


def get_category_for_mixin(mixin_name: str) -> type | None:
    """Возвращает Protocol-класс категории для mixin'а, или None если не найден.

    Example:
        >>> get_category_for_mixin("EIPMixin")
        <class 'src.backend.dsl.builders.protocols.EIPProtocol'>
    """
    return _CATEGORY_MAP.get(mixin_name)


def get_protocol_for_category(category_name: str) -> type | None:
    """Возвращает Protocol-класс по имени категории (``ControlFlow``, ``EIP`` и т.д.)."""
    name = f"{category_name}Protocol"
    if name in globals():
        return globals()[name]
    return None


def is_runtime_protocol_conformant(
    instance: RouteBuilder, category_name: str,
) -> bool:
    """Проверяет, что в MRO ``instance`` присутствуют ВСЕ mixin'ы данной категории.

    Использует identity (``is``), а не name-сравнение: ``TransportSourcesMixin``
    и ``SourcesMixin`` — одна и та же class (alias), и проверка должна
    корректно работать независимо от того, как mixin re-exported.

    Use case: диагностика — если ``is_runtime_protocol_conformant(rb, "EIP")`` вернёт
    False, значит какие-то EIP-mixin'ы не подключены в текущем builder'е.

    Example:
        >>> from src.backend.dsl.builders.base import RouteBuilder
        >>> from src.backend.dsl.builders.protocols import is_runtime_protocol_conformant
        >>> rb = RouteBuilder("test", source="timer:60s")
        >>> is_runtime_protocol_conformant(rb, "EIP")
        True
    """
    proto = get_protocol_for_category(category_name)
    if proto is None:
        return False
    expected_mixin_names = {
        name for name, cat in _CATEGORY_MAP.items() if cat is proto
    }
    # Resolve expected name → actual class object (handles aliases like
    # TransportSourcesMixin ↔ SourcesMixin).
    expected_classes: set[type] = set()
    for name in expected_mixin_names:
        from src.backend.dsl.builders import base as _base
        cls = getattr(_base, name, None)
        if cls is not None:
            expected_classes.add(cls)
    actual_classes = set(type(instance).__mro__)
    return expected_classes.issubset(actual_classes)


__all__ = (
    "AIAgentProtocol",
    "ControlFlowProtocol",
    "DataStoreProtocol",
    "EIPProtocol",
    "InfrastructureProtocol",
    "MessagingProtocol",
    "ResilienceProtocol",
    "TransportProtocol",
    "get_category_for_mixin",
    "get_protocol_for_category",
    "is_runtime_protocol_conformant",
)


# Sanity-check: ровно 36 top-level mixin'ов должно быть в map.
# ``SourcesMixin`` — это re-export alias ``TransportSourcesMixin`` (см.
# ``base/__init__.py:77-79``), не отдельный mixin, поэтому НЕ в map.
assert len(_CATEGORY_MAP) == 36, (
    f"Expected 36 entries in _CATEGORY_MAP (one per top-level mixin), "
    f"got {len(_CATEGORY_MAP)} — update map"
)
# All 8 categories must be present.
assert len({cat for cat in _CATEGORY_MAP.values()}) == 8, (
    f"Expected 8 distinct categories, got {len(set(_CATEGORY_MAP.values()))}"
)
