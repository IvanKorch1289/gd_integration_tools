from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

"""Base-модуль RouteBuilder.

Содержит сам класс ``RouteBuilder`` (``@dataclass(slots=True)``) и его
core-методы: точки входа, ``_add`` / ``_add_lazy`` helpers, pipeline
composition (process / to / process_fn / include), chainable per-step
modifiers (with_timeout/retries/headers/auth), core-процессоры
(set_header/set_property/log/validate/feature_flag),
generic-helpers (shadow_mode/bulkhead/lineage/ab_test/feature_flag_branch),
business-helpers (tenant_scope/cost_tracker/outbox/mask/compliance_labels),
а также ``build()`` + ``_validate_action_names()``.

Контракт миксинов (см. ADR DSL Foundation Refactor 2026-05):

* mixin'ы — **stateless** поведенческие классы: только методы.
* mixin'ы **не имеют** ``@dataclass`` декоратора.
* mixin'ы **объявляют** пустой ``__slots__ = ()`` — обязательно для
  совместимости с ``RouteBuilder(@dataclass(slots=True))``: пустой tuple
  снимает ``__dict__`` overhead, не конфликтует с lay-out наследника
  и проходит ``mypy`` strict.
* mixin'ы **не имеют** instance-атрибутов; всё состояние живёт в
  ``RouteBuilder`` (``route_id``, ``source``, ``description``,
  ``_processors``, ``_protocol``, ``_transport_config``,
  ``_feature_flag``).
* приватные утилиты (``_add``, ``_add_lazy``, ``_last_processor_or_raise``,
  ``_set_first_attr``, ``_validate_action_names``) живут на
  ``RouteBuilder`` и доступны через ``self``.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.backend.dsl.adapters.types import ProtocolType, TransportConfig
from src.backend.dsl.builders.agent_dsl import AgentDSLMixin
from src.backend.dsl.builders.ai_rpa import AIRPAMixin
from src.backend.dsl.builders.batch import BatchMixin
from src.backend.dsl.builders.collection import CollectionMixin
from src.backend.dsl.builders.content import ContentMixin
from src.backend.dsl.builders.content_mixin import EIPContentMixin
from src.backend.dsl.builders.control_flow import ControlFlowMixin
from src.backend.dsl.builders.converters import ConvertersMixin
from src.backend.dsl.builders.converters_mixin import FormatConvertersMixin
from src.backend.dsl.builders.data_store import DataStoreStepMixin
from src.backend.dsl.builders.data_store_mixin import DataStoreMixin
from src.backend.dsl.builders.deferred_execution_mixin import DeferredExecutionMixin
from src.backend.dsl.builders.eip import EIPMixin
from src.backend.dsl.builders.eventbus_mixin import EventBusMixin
from src.backend.dsl.builders.infrastructure_dsl import InfrastructureDSL
from src.backend.dsl.builders.integration import IntegrationMixin
from src.backend.dsl.builders.notebook import NotebookMixin
from src.backend.dsl.builders.request_reply import RequestReplyMixin
from src.backend.dsl.builders.saga_lra import SagaLRAMixin
from src.backend.dsl.builders.template_engine import TemplateEngineChainMixin
from src.backend.dsl.builders.template_engine_mixin import TemplateEngineMixin
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors import (
    BaseProcessor,
    CallableProcessor,
    LogProcessor,
    ProcessorCallable,
    SetHeaderProcessor,
    SetPropertyProcessor,
    ValidateProcessor,
)
from src.backend.dsl.processors.plan_execute_processor import PlanExecuteMixin
from src.backend.dsl.processors.reflection_loop_processor import ReflectionLoopMixin
from src.backend.dsl.processors.router_specialist_processor import RouterSpecialistMixin

class ResilienceMixin:
    """resilience (bulkhead, cost_tracker, outbox) для RouteBuilder. S57 W1 extraction."""

    __slots__ = ()

    def bulkhead(
        self,
        name: str,
        limit: int,
        processors: list[BaseProcessor],
        *,
        wait: bool = True,
        timeout: float | None = None,
    ) -> RouteBuilder:
        """Ограничивает concurrency на ветку — защита провайдера от перегрузки."""
        from src.backend.dsl.engine.processors.generic import BulkheadProcessor

        return self._add(
            BulkheadProcessor(
                name=name,
                limit=limit,
                processors=processors,
                wait=wait,
                timeout=timeout,
            )
        )

    def cost_tracker(self) -> RouteBuilder:
        """Инициализация cost-словаря в properties (LLM-токены, HTTP, DB, USD)."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.business", "CostTrackerProcessor"
        )

    def outbox(self, *, topic: str) -> RouteBuilder:
        """Transactional Outbox: запись события в outbox-таблицу."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.business", "OutboxProcessor", topic=topic
        )

