from __future__ import annotations
from __future__ import annotations
"""RouteBuilder package (S57 W1 decomp from base.py 648 LOC).
32 methods decomposed в 7 mixin files:
- fluent_mixin.py (5), config_mixin.py (5), validation_mixin.py (4)
- deps_mixin.py (1), feature_mixin.py (4)
- resilience_mixin.py (3), compliance_mixin.py (4)
Core (6) остается в __init__.py: from_, from_registered_source, _add, _add_lazy, process, build.
Backward-compat: ``from src.backend.dsl.builders.base import RouteBuilder`` works.
"""
from typing import TYPE_CHECKING, Any
from src.backend.core.logging import get_logger
if TYPE_CHECKING:
    pass
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
logger = get_logger(__name__)
from src.backend.dsl.builders.base.fluent_mixin import FluentMixin  # S57 W1: MRO
from src.backend.dsl.builders.base.config_mixin import ConfigMixin  # S57 W1: MRO
from src.backend.dsl.builders.base.validation_mixin import ValidationMixin  # S57 W1: MRO
from src.backend.dsl.builders.base.deps_mixin import DepsMixin  # S57 W1: MRO
from src.backend.dsl.builders.base.feature_mixin import FeatureMixin  # S57 W1: MRO
from src.backend.dsl.builders.base.resilience_mixin import ResilienceMixin  # S57 W1: MRO
from src.backend.dsl.builders.base.compliance_mixin import ComplianceMixin  # S57 W1: MRO
__all__ = (
    "RouteBuilder",
    "get_route_builder",
)
class RouteBuilder(
    AIRPAMixin,
    BatchMixin,
    CollectionMixin,
    EIPContentMixin,
    ContentMixin,
    ControlFlowMixin,
    DataStoreStepMixin,
    DataStoreMixin,
    DeferredExecutionMixin,
    EIPMixin,
    EventBusMixin,
    IntegrationMixin,
    ConvertersMixin,
    FormatConvertersMixin,
    RequestReplyMixin,
    SagaLRAMixin,
    TemplateEngineChainMixin,
    TemplateEngineMixin,
    InfrastructureDSL,
    AgentDSLMixin,
    PlanExecuteMixin,
    ReflectionLoopMixin,
    RouterSpecialistMixin,
    FluentMixin,
    ConfigMixin,
    ValidationMixin,
    DepsMixin,
    FeatureMixin,
    ResilienceMixin,
    ComplianceMixin,
):
    """RouteBuilder — DSL core (7 mixins = 26 methods + 6 core)."""
    __slots__ = ()
    @classmethod
    def from_(
        cls, route_id: str, source: str, *, description: str | None = None
    ) -> RouteBuilder:
        """Точка входа: создаёт новый RouteBuilder.
        Args:
            route_id: Уникальный ID маршрута (e.g., "orders.create").
            source: Источник данных (e.g., "internal:orders", "timer:60s", "webhook:/path").
            description: Человекочитаемое описание маршрута.
        Returns:
            RouteBuilder для fluent-chain вызовов.
        Example::
            route = (
                RouteBuilder.from_("etl.import", source="timer:300s")
                .http_call("https://api.example.com/data")
                .normalize()
                .dispatch_action("analytics.insert_batch")
                .build()
            )
        """
        return cls(route_id=route_id, source=source, description=description)
    @classmethod
    def from_registered_source(
        cls, route_id: str, source_id: str, *, description: str | None = None
    ) -> RouteBuilder:
        """Точка входа W23: маршрут запитывается от зарегистрированного Source.
        Связь Source → DSL делается на уровне ``services.sources.lifecycle``
        через :class:`SourceToInvokerAdapter`; этот метод нужен только
        для **декларации** в DSL ("этот route ждёт события от source X")
        и метаданных ``Pipeline``.
        Args:
            route_id: Уникальный ID маршрута.
            source_id: ID source-инстанса в :class:`SourceRegistry`.
            description: Человекочитаемое описание.
        Example::
            route = (
                RouteBuilder.from_registered_source("orders.audit", "orders_cdc")
                .normalize()
                .dispatch_action("analytics.insert_batch")
                .build()
            )
        """
        return cls(
            route_id=route_id, source=f"source:{source_id}", description=description
        )
    def _add(self, processor: BaseProcessor) -> RouteBuilder:
        self._processors.append(processor)
        return self
    def _add_lazy(
        self, import_path: str, class_name: str, **kwargs: Any
    ) -> RouteBuilder:
        """Lazy import + создание процессора. Для AI/Web/Export/Integration."""
        import importlib
        mod = importlib.import_module(import_path)
        cls = getattr(mod, class_name)
        return self._add(cls(**kwargs))
    def process(self, processor: BaseProcessor) -> RouteBuilder:
        """Добавляет произвольный процессор в pipeline."""
        return self._add(processor)
    def build(self, *, validate_actions: bool = True) -> Pipeline:
        """Собирает Pipeline из накопленных процессоров.
        Финальный вызов в fluent-chain.
        Args:
            validate_actions: Если True (default), проверяет что все
                dispatch_action имена зарегистрированы в ActionHandlerRegistry.
                Raises ValueError с подсказкой схожих имён при опечатке.
        """
        if validate_actions:
            self._validate_action_names()
        return Pipeline(
            route_id=self.route_id,
            source=self.source,
            description=self.description,
            processors=list(self._processors),
            protocol=self._protocol,
            transport_config=self._transport_config,
            feature_flag=self._feature_flag,
        )