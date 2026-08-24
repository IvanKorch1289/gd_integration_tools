"""RouteBuilder package (S57 W1 decomp from base.py 648 LOC).

76 mixin-классов в MRO (36 top-level declared в class-decl ниже + 42
sub-mixin'а от composite-mixin'ов: ``IntegrationMixin``, ``AgentDSLMixin``,
``EIPMixin``, ``TransportSourcesMixin``, ``AIRPAMixin``,
``IntegrationCoreMixin`` и т.д.).
Ядро (6 core-методов) остаётся в этом ``__init__.py``:
``from_``, ``from_registered_source``, ``_add``, ``_add_lazy``, ``process``,
``build``. Decomp pattern: god-class → mixin-tree, чтобы новые фичи
добавлялись отдельным mixin-файлом без правки RouteBuilder MRO.

Backward-compat: ``from src.backend.dsl.builders.base import RouteBuilder`` works.
"""

from __future__ import annotations as annotations

from typing import TYPE_CHECKING as TYPE_CHECKING
from typing import Any as Any

if TYPE_CHECKING:
    pass
from src.backend.dsl.builders.agent_dsl import AgentDSLMixin as AgentDSLMixin
from src.backend.dsl.builders.ai_rpa import AIRPAMixin as AIRPAMixin
from src.backend.dsl.builders.base.compliance_mixin import (
    ComplianceMixin,  # S57 W1: MRO
)
from src.backend.dsl.builders.base.config_mixin import (
    ConfigMixin,  # S57 W1: MRO as ConfigMixin  # S57 W1: MRO
)
from src.backend.dsl.builders.base.deps_mixin import (
    DepsMixin,  # S57 W1: MRO as DepsMixin  # S57 W1: MRO
)
from src.backend.dsl.builders.base.feature_mixin import (
    FeatureMixin,  # S57 W1: MRO as FeatureMixin  # S57 W1: MRO
)
from src.backend.dsl.builders.base.fluent_mixin import (
    FluentMixin,  # S57 W1: MRO as FluentMixin  # S57 W1: MRO
)
from src.backend.dsl.builders.base.middleware_mixin import (
    MiddlewareMixin,  # S57 W1: MRO
)
from src.backend.dsl.builders.base.resilience_mixin import (
    ResilienceMixin,  # S57 W1: MRO
)
from src.backend.dsl.builders.base.validation_mixin import (
    ValidationMixin,  # S57 W1: MRO
)
from src.backend.dsl.builders.batch import BatchMixin as BatchMixin
from src.backend.dsl.builders.collection import CollectionMixin as CollectionMixin
from src.backend.dsl.builders.content import ContentMixin as ContentMixin
from src.backend.dsl.builders.content_mixin import EIPContentMixin as EIPContentMixin
from src.backend.dsl.builders.control_flow import ControlFlowMixin as ControlFlowMixin
from src.backend.dsl.builders.converters import ConvertersMixin as ConvertersMixin
from src.backend.dsl.builders.converters_mixin import (
    FormatConvertersMixin as FormatConvertersMixin,
)
from src.backend.dsl.builders.data_store import DataStoreStepMixin as DataStoreStepMixin
from src.backend.dsl.builders.data_store_mixin import DataStoreMixin as DataStoreMixin
from src.backend.dsl.builders.deferred_execution_mixin import (
    DeferredExecutionMixin as DeferredExecutionMixin,
)
from src.backend.dsl.builders.eip import EIPMixin as EIPMixin
from src.backend.dsl.builders.eventbus_mixin import EventBusMixin as EventBusMixin
from src.backend.dsl.builders.infrastructure_dsl import (
    InfrastructureDSL as InfrastructureDSL,
)
from src.backend.dsl.builders.integration import IntegrationMixin as IntegrationMixin
from src.backend.dsl.builders.ip_restriction_mixin import (
    IPRestrictionMixin as IPRestrictionMixin,
)
from src.backend.dsl.builders.notebook import NotebookMixin as NotebookMixin
from src.backend.dsl.builders.policy_mixin import PolicyMixin as PolicyMixin
from src.backend.dsl.builders.request_reply import (
    RequestReplyMixin as RequestReplyMixin,
)
from src.backend.dsl.builders.saga_lra import SagaLRAMixin as SagaLRAMixin
from src.backend.dsl.builders.sources_mixin import (
    SourcesMixin as TransportSourcesMixin,  # S97 W1: SSE, CDC, messaging, ...
)
from src.backend.dsl.builders.template_engine import (
    TemplateEngineChainMixin as TemplateEngineChainMixin,
)
from src.backend.dsl.builders.template_engine_mixin import (
    TemplateEngineMixin as TemplateEngineMixin,
)
from src.backend.dsl.builders.variable_mixin import VariableMixin as VariableMixin
from src.backend.dsl.engine.pipeline import Pipeline as Pipeline
from src.backend.dsl.engine.processors import BaseProcessor as BaseProcessor
from src.backend.dsl.processors.plan_execute_processor import (
    PlanExecuteMixin as PlanExecuteMixin,
)
from src.backend.dsl.processors.reflection_loop_processor import (
    ReflectionLoopMixin as ReflectionLoopMixin,
)
from src.backend.dsl.processors.router_specialist_processor import (
    RouterSpecialistMixin as RouterSpecialistMixin,
)

__all__ = ("RouteBuilder", "get_route_builder")


class RouteBuilder(  # type: ignore[misc]
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
    NotebookMixin,  # S168 W9 P0-3: wired per ARCHITECTURAL_AUDIT_V2.md:102-117
    VariableMixin,  # S168 W9 P0-3
    PolicyMixin,  # S168 W9 P0-3
    FluentMixin,
    ConfigMixin,
    ValidationMixin,
    DepsMixin,
    FeatureMixin,
    ResilienceMixin,
    ComplianceMixin,
    MiddlewareMixin,
    IPRestrictionMixin,
    TransportSourcesMixin,  # S97 W1: SSE/CDC/messaging builders (orphan в S94)
):
    """RouteBuilder — DSL core (76 mixin-классов в MRO + 6 core-методов).

    Composition (см. class-decl выше): AIRPAMixin, BatchMixin,
    CollectionMixin, EIPContentMixin, ContentMixin, ControlFlowMixin,
    DataStoreStepMixin, DataStoreMixin, DeferredExecutionMixin, EIPMixin,
    EventBusMixin, IntegrationMixin, ConvertersMixin, FormatConvertersMixin,
    RequestReplyMixin, SagaLRAMixin, TemplateEngineChainMixin,
    TemplateEngineMixin, InfrastructureDSL, AgentDSLMixin, PlanExecuteMixin,
    ReflectionLoopMixin, RouterSpecialistMixin, NotebookMixin, VariableMixin,
    PolicyMixin, FluentMixin, ConfigMixin, ValidationMixin, DepsMixin,
    FeatureMixin, ResilienceMixin, ComplianceMixin, MiddlewareMixin,
    IPRestrictionMixin, TransportSourcesMixin.

    S168 W9 P0-3: added NotebookMixin, VariableMixin, PolicyMixin to MRO
    (per ARCHITECTURAL_AUDIT_V2.md:102-117). Раньше они были defined
    but not wired → fluent DSL chain ``route.notebook_execute()`` /
    ``route.set_variable()`` / ``route.policy.cache()`` выбрасывали
    AttributeError. Теперь доступны как route-level methods.
    """

    __slots__ = (
        "_description",
        "_feature_flag",
        "_middlewares",
        "_processors",
        "_protocol",
        "_route_overrides",  # S163 W14: dict for route-level overrides
        "_transport_config",
        "description",
        "route_id",
        "source",
    )

    def __init__(
        self, route_id: str = "", source: str = "", description: str | None = None
    ) -> None:
        """S97 W1: explicit __init__ чтобы ``cls(route_id=..., ...)`` работал.

        Pre-S97: ``RouteBuilder`` имел ``__slots__=()`` и **нет** ``__init__``,
        поэтому ``from_`` (``cls(route_id=..., source=..., description=...)``)
        → ``TypeError: RouteBuilder() takes no arguments``. Все 12+ ``from_*``
        builders (CDC, SSE, HTTP, messaging, ...) TypeError на instantiation.

        Fix: slots с явными атрибутами (slot'ы требуют declaration),
        ``__init__`` с keyword-only args (default values для backward compat
        с ``cls()`` no-args pattern). Атрибуты с префиксом ``_`` —
        internal state (``_processors``, ``_protocol``), без префикса —
        public API (``route_id``, ``source``, ``description``) для ``build()``.
        """
        object.__setattr__(self, "route_id", route_id)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "_description", description or "")
        object.__setattr__(self, "_middlewares", [])
        object.__setattr__(self, "_processors", [])
        object.__setattr__(self, "_protocol", None)
        object.__setattr__(self, "_transport_config", None)
        object.__setattr__(self, "_feature_flag", None)
        object.__setattr__(self, "_route_overrides", {})  # S163 W14

    # D-AUDIT-20402 (cycle 204 Tier 3): ``__getattr__`` fallback для missing
    # attributes. Python invokes ``__getattr__`` только если normal lookup
    # fails (MRO + ``__slots__`` не нашли attr). Цель — **diagnostic**:
    # если разработчик вызывает ``route.foo()`` и ``foo`` нет — дать
    # информативную ошибку со ссылкой на protocols catalog (8 категорий).
    #
    # Perf impact: <0.1 us для *missing* attrs (Python check перед raise).
    # Для *existing* attrs overhead = 0 (Python never calls ``__getattr__``
    # если normal lookup succeeded). Поэтому 76-mixin MRO perf baseline
    # (cycle 202) не меняется для hot paths.
    def __getattr__(self, name: str) -> Any:
        """Diagnostic fallback для missing attributes (cycle 204 Tier 3).

        Raises informative ``AttributeError`` with:
        - имя запрошенного attr
        - ссылка на protocols catalog (8 categories)
        - hint для поиска в правильной mixin-категории

        Не предназначен для lazy-loading — это **pure diagnostic**.
        Если attr действительно нужен как method, добавьте mixin в
        ``src/backend/dsl/builders/`` и update ``protocols.py`` map.
        """
        # Skip dunder / private — they are framework-level attrs, не user-facing.
        if name.startswith("_") and name != "__":
            raise AttributeError(
                f"{type(self).__name__!r} object has no attribute {name!r}"
            )

        # Попытка найти ближайший mixin с похожим именем (Levenshtein ≤3).
        # Если найден — подсказать категорию через protocols catalog.
        from src.backend.dsl.builders.protocols import get_category_for_mixin

        _mixin_names = [
            c.__name__ for c in type(self).__mro__ if c.__name__.endswith("Mixin")
        ]
        _hint = None
        for _mname in _mixin_names:
            if abs(len(_mname) - len(name)) <= 3 and _shares_prefix(_mname, name):
                _cat = get_category_for_mixin(_mname)
                if _cat is not None:
                    _hint = f" (похоже на {_mname!r} из {_cat.__name__})"
                    break

        _msg = (
            f"{type(self).__name__!r} object has no attribute {name!r}. "
            f"RouteBuilder имеет 76 mixins в MRO — см. "
            f"src/backend/dsl/builders/protocols.py для category index."
        )
        if _hint:
            _msg += _hint
        raise AttributeError(_msg)

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

        S163 W15: копирует ``self._route_overrides`` в Pipeline для handlers
        (ws_handler/grpc_server/graphql) — per-route override settings.

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
            middlewares=list(self._middlewares),
            route_overrides=dict(self._route_overrides),  # S163 W15
        )


# Cycle 30 P4-#4: Protocol interfaces documenting RouteBuilder contract.
# These are NOT the composition refactor (which would break 200+ tests
# and require multi-week migration), but they document the public API
# surface that a future CompositionRouteBuilder must satisfy.
#
# Migration path (per Master Prompt P4-#4):
# 1. Protocol definitions (this commit) -- documents contract.
# 2. CompositionRouteBuilder alongside RouteBuilder -- parallel impl.
# 3. Gradual migration of callers from RouteBuilder to CompositionRouteBuilder.
# 4. Eventually RouteBuilder becomes a thin wrapper or is removed.

from typing import Protocol as _Protocol
from typing import runtime_checkable as _runtime_checkable


def _shares_prefix(a: str, b: str, n: int = 3) -> bool:
    """True если ``a`` и ``b`` имеют общий prefix длиной ≥ ``n``.

    Helper для ``__getattr__`` diagnostic (cycle 204 Tier 3):
    если запрошенный attr похож на mixin-name — suggest category.
    """
    if len(a) < n or len(b) < n:
        return False
    return a[:n].lower() == b[:n].lower()


@_runtime_checkable
class _RouteProcessorSteps(_Protocol):
    """Contract: processor chain management."""

    def _add_processor(self, processor: Any) -> Any: ...
    def _add_lazy(self, module: str, cls_name: str, **kwargs: Any) -> Any: ...


@_runtime_checkable
class _RouteCore(_Protocol):
    """Contract: core route identity + output."""

    @property
    def route_id(self) -> str: ...
    def to(self, sink: str, **kwargs: Any) -> Any: ...
    def log(self, level: str = "info", message: str = "") -> Any: ...


# Cycle 244: 18 additional Protocol classes documenting the full RouteBuilder
# contract surface. Каждый Protocol структурно (typing.Protocol) описывает
# 5-15 cohesive-методов из одного mixin/категории, чтобы:
# 1) downstream code мог type-check против ``RouteBuilder`` через ``isinstance``
#    (runtime_checkable);
# 2) документация категоризирует 76 mixin-методов для IDE/help;
# 3) CompositionRouteBuilder (master prompt P4-#4 migration path) имеет
#    explicit surface для постепенного внедрения.
#
# Convention: имя ``_<Категория>_Protocol``, ``@_runtime_checkable``, docstring
# one-liner, минимально-валидные сигнатуры (return Any для fluent-chain).


@_runtime_checkable
class _RouteEntityCrudProtocol(_Protocol):
    """Contract: entity CRUD операции (entity_*/crud_* aliases)."""

    def entity_create(
        self,
        *,
        entity: str,
        payload_from: str = "body",
        result_property: str = "action_result",
    ) -> Any: ...
    def entity_get(
        self,
        *,
        entity: str,
        id_from: str = "body.id",
        result_property: str = "action_result",
    ) -> Any: ...
    def entity_update(
        self,
        *,
        entity: str,
        id_from: str = "body.id",
        payload_from: str = "body",
        result_property: str = "action_result",
    ) -> Any: ...
    def entity_delete(
        self,
        *,
        entity: str,
        id_from: str = "body.id",
        result_property: str = "action_result",
    ) -> Any: ...
    def entity_list(
        self,
        *,
        entity: str,
        filters_from: str | None = "body.filters",
        page: int | None = None,
        size: int | None = None,
        result_property: str = "action_result",
    ) -> Any: ...
    def crud_create(
        self,
        entity: str,
        *,
        payload_from: str = "body",
        result_property: str = "action_result",
    ) -> Any: ...
    def crud_read(
        self,
        entity: str,
        *,
        id_from: str = "body.id",
        result_property: str = "action_result",
    ) -> Any: ...
    def crud_update(
        self,
        entity: str,
        *,
        id_from: str = "body.id",
        payload_from: str = "body",
        result_property: str = "action_result",
    ) -> Any: ...
    def crud_delete(
        self,
        entity: str,
        *,
        id_from: str = "body.id",
        result_property: str = "action_result",
    ) -> Any: ...
    def crud_list(
        self,
        entity: str,
        *,
        filters_from: str | None = "body.filters",
        page: int | None = None,
        size: int | None = None,
        result_property: str = "action_result",
    ) -> Any: ...


@_runtime_checkable
class _RouteBatchDataProtocol(_Protocol):
    """Contract: batch-DB + in-memory KV (batch_*/data_store_*)."""

    def batch_insert(
        self,
        table: str,
        items: list[dict[str, Any]] | None = None,
        *,
        profile: str = "default",
    ) -> Any: ...
    def batch_update(
        self,
        table: str,
        items: list[dict[str, Any]] | None = None,
        *,
        key_field: str = "id",
        profile: str = "default",
    ) -> Any: ...
    def batch_delete(
        self,
        table: str,
        ids: list[Any] | None = None,
        *,
        key_field: str = "id",
        profile: str = "default",
    ) -> Any: ...
    def data_store_set(self, key: str, value: Any) -> Any: ...
    def data_store_get(
        self,
        key: str,
        *,
        default: Any = None,
        result_property: str = "data_store_value",
    ) -> Any: ...
    def data_store_delete(self, key: str) -> Any: ...
    def data_store(self, name: str = "default", backend: str = "memory") -> Any: ...


@_runtime_checkable
class _RouteControlFlowProtocol(_Protocol):
    """Contract: control-flow (choice/switch/try/retry/fallback/DLQ/saga)."""

    def choice(self, when: list[Any], otherwise: list[Any] | None = None) -> Any: ...
    def switch(
        self,
        field: str,
        cases: dict[str, list[Any]],
        *,
        default: list[Any] | None = None,
    ) -> Any: ...
    def do_try(
        self,
        try_processors: list[Any],
        catch_processors: list[Any] | None = None,
        finally_processors: list[Any] | None = None,
    ) -> Any: ...
    def retry(
        self,
        processors: list[Any],
        *,
        max_attempts: int = 3,
        delay_seconds: float = 1.0,
        backoff: str = "exponential",
    ) -> Any: ...
    def fallback(self, processors: list[Any]) -> Any: ...
    def dead_letter(
        self, processors: list[Any], *, dlq_stream: str = "dsl-dlq"
    ) -> Any: ...
    def on_error(
        self,
        *,
        action: str | None = None,
        processors: list[Any] | None = None,
        dlq_stream: str = "dsl-dlq",
    ) -> Any: ...
    def saga(self, steps: list[Any]) -> Any: ...


@_runtime_checkable
class _RouteConcurrencyProtocol(_Protocol):
    """Contract: parallel / fork-join / loop / for-each / throttling."""

    def parallel(
        self, branches: dict[str, list[Any]], *, strategy: str = "all"
    ) -> Any: ...
    def fork_join(
        self,
        branches: dict[str, list[Any]],
        *,
        aggregation: str = "collect",
        timeout_seconds: float | None = None,
    ) -> Any: ...
    def idempotent(self, key_expression: Any, *, ttl_seconds: int = 86400) -> Any: ...
    def throttle(self, rate: float, *, burst: int = 1) -> Any: ...
    def delay(
        self, delay_ms: int | None = None, *, scheduled_time_fn: Any | None = None
    ) -> Any: ...
    def loop(
        self,
        processors: list[Any],
        *,
        count: int | None = None,
        until: Any | None = None,
        max_iterations: int = 1000,
    ) -> Any: ...
    def for_each(
        self,
        items_path: str,
        processors: list[Any],
        *,
        copy_exchange: bool = True,
        max_iterations: int = 10000,
    ) -> Any: ...


@_runtime_checkable
class _RouteTimeResilienceProtocol(_Protocol):
    """Contract: time-control / circuit-breaker / expiration / HITL."""

    def circuit_breaker(
        self,
        processors: list[Any],
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        fallback_processors: list[Any] | None = None,
        breaker_name: str | None = None,
    ) -> Any: ...
    def timeout(
        self,
        processors: list[Any],
        *,
        seconds: float = 30.0,
        fallback_processors: list[Any] | None = None,
    ) -> Any: ...
    def expire(
        self,
        ttl_seconds: float,
        *,
        header_name: str = "x-created-at",
        drop_action: str = "fail",
    ) -> Any: ...
    def correlation_id(self, *, header: str = "x-correlation-id") -> Any: ...
    def hitl_approval(
        self,
        hitl_service: Any,
        *,
        title: str,
        description: str = "",
        approvers: list[str] | None = None,
        timeout_seconds: float = 86_400.0,
        payload_path: str | None = None,
        request_info_processors: list[Any] | None = None,
    ) -> Any: ...
    def region_routing(
        self,
        primary: str,
        fallback: str | None = None,
        *,
        health_check_interval: float = 30.0,
    ) -> Any: ...
    def supervisor(
        self, *, max_restarts: int = 3, timeout: float = 60.0, backoff: float = 2.0
    ) -> Any: ...


@_runtime_checkable
class _RouteDbProtocol(_Protocol):
    """Contract: SQL DML/DQL (db_query/db_insert/update/upsert/delete/execute_dml/external/jdbc)."""

    def db_query(self, sql: str, *, result_property: str = "db_result") -> Any: ...
    def db_insert(
        self,
        table: str,
        data: dict[str, Any],
        *,
        result_property: str = "db_crud_result",
    ) -> Any: ...
    def db_update(
        self,
        table: str,
        data: dict[str, Any],
        where: dict[str, Any],
        *,
        result_property: str = "db_crud_result",
    ) -> Any: ...
    def db_upsert(
        self,
        table: str,
        data: dict[str, Any],
        conflict_keys: list[str],
        *,
        result_property: str = "db_crud_result",
    ) -> Any: ...
    def execute_dml(
        self,
        operation: str,
        table: str,
        *,
        dialect: str = "postgresql",
        data: dict[str, Any] | None = None,
        where: dict[str, Any] | None = None,
        conflict_keys: list[str] | None = None,
        result_property: str = "db_crud_result",
    ) -> Any: ...
    def db_delete(
        self,
        table: str,
        where: dict[str, Any],
        *,
        result_property: str = "db_crud_result",
    ) -> Any: ...
    def db_query_external(
        self,
        profile: str,
        sql: str,
        *,
        params_from: str = "body",
        result_property: str = "db_result",
        fetch: str = "all",
        commit: bool = False,
    ) -> Any: ...
    def jdbc_query(
        self,
        sql: str,
        profile: str,
        *,
        params_from: str = "body",
        result_property: str = "jdbc_result",
    ) -> Any: ...


@_runtime_checkable
class _RoutePersistenceProtocol(_Protocol):
    """Contract: stored-proc + file/S3 + lookup + merge."""

    def db_call_procedure(
        self,
        profile: str,
        name: str,
        *,
        schema: str = "public",
        params_from: str = "body",
        result_property: str = "sp_result",
        dialect: str = "postgres",
    ) -> Any: ...
    def file_move(
        self, src: str | None = None, dst: str | None = None, *, mode: str = "copy"
    ) -> Any: ...
    def read_file(self, path: str | None = None, *, binary: bool = False) -> Any: ...
    def write_file(self, path: str | None = None, *, format: str = "auto") -> Any: ...
    def read_s3(self, bucket: str | None = None, key: str | None = None) -> Any: ...
    def write_s3(
        self,
        bucket: str | None = None,
        key: str | None = None,
        *,
        content_type: str = "application/octet-stream",
    ) -> Any: ...
    def lookup(
        self, key_from: str, *, target: str, result_property: str = "lookup_result"
    ) -> Any: ...
    def merge(
        self,
        source_property: str,
        *,
        target_property: str = "merge_result",
        strategy: str = "merge_dicts",
    ) -> Any: ...


@_runtime_checkable
class _RouteProxyProtocol(_Protocol):
    """Contract: proxy / redirect / external HTTP/GraphQL/LDAP."""

    def expose_proxy(
        self,
        src: str,
        *,
        methods: list[str] | None = None,
        header_map: dict[str, Any] | None = None,
    ) -> Any: ...
    def forward_to(
        self,
        dst: str,
        *,
        pass_headers: bool = True,
        header_map: dict[str, Any] | None = None,
        rewrite_path: str | None = None,
        timeout: float = 30.0,
    ) -> Any: ...
    def proxy(
        self,
        src: str,
        dst: str,
        *,
        methods: list[str] | None = None,
        pass_headers: bool = True,
        header_map: dict[str, Any] | None = None,
        rewrite_path: str | None = None,
        timeout: float = 30.0,
    ) -> Any: ...
    def redirect(
        self,
        target_url: str | None = None,
        *,
        status_code: int = 302,
        url_source: str | None = None,
        source_key: str | None = None,
        allowed_hosts: list[str] | None = None,
    ) -> Any: ...
    def http_call(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        auth_token: str | None = None,
        timeout: float = 30.0,
        result_property: str | None = None,
    ) -> Any: ...
    def graphql_query(
        self,
        endpoint: str,
        query: str,
        *,
        variables: dict[str, Any] | None = None,
        operation_name: str | None = None,
        headers: dict[str, str] | None = None,
        auth_token: str | None = None,
        auth_header: str = "Authorization",
        timeout: float = 30.0,
        result_property: str | None = None,
    ) -> Any: ...
    def ldap_query(
        self,
        server: str,
        base_dn: str,
        filter: str = "(objectClass=*)",
        *,
        attributes: list[str] | None = None,
        username: str | None = None,
        password: str | None = None,
        use_ssl: bool = False,
        timeout: float = 30.0,
        result_property: str = "ldap_result",
    ) -> Any: ...
    def geo(
        self,
        mode: str,
        *,
        address: str | None = None,
        point_a: tuple[float, float] | None = None,
        point_b: tuple[float, float] | None = None,
        to: str = "body.geo_result",
    ) -> Any: ...


@_runtime_checkable
class _RouteSinkProtocol(_Protocol):
    """Contract: outbound sinks (10 sink_* методов)."""

    def sink_http(
        self,
        *,
        url: str,
        method: str = "POST",
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
    ) -> Any: ...
    def sink_email(
        self,
        *,
        host: str,
        from_addr: str,
        port: int = 587,
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = False,
        start_tls: bool = True,
        default_to: str | None = None,
        default_subject: str = "",
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
    ) -> Any: ...
    def sink_file(
        self,
        *,
        path: str,
        mode: str = "append",
        encoding: str = "utf-8",
        ensure_dir: bool = True,
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
    ) -> Any: ...
    def sink_grpc(
        self,
        *,
        target: str,
        full_method: str,
        secure: bool = True,
        timeout: float = 10.0,
        payload_property: str | None = None,
        result_property: str = "grpc_result",
    ) -> Any: ...
    def sink_mq(
        self,
        *,
        broker: str,
        url: str,
        topic: str,
        extra: dict[str, Any] | None = None,
        payload_property: str | None = None,
        result_property: str = "mq_publish_result",
    ) -> Any: ...
    def sink_mqtt(
        self,
        *,
        host: str,
        topic: str,
        port: int | None = None,
        qos: int = 0,
        retain: bool = False,
        username: str | None = None,
        password: str | None = None,
        payload_property: str | None = None,
        result_property: str = "mqtt_publish_result",
    ) -> Any: ...
    def sink_s3(
        self,
        *,
        bucket: str,
        key: str,
        content_type: str = "application/octet-stream",
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
    ) -> Any: ...
    def sink_soap(
        self,
        *,
        wsdl_url: str,
        operation: str,
        service_name: str | None = None,
        port_name: str | None = None,
        timeout: float = 30.0,
        payload_property: str | None = None,
        result_property: str = "soap_result",
    ) -> Any: ...
    def sink_webhook(
        self,
        *,
        url: str,
        event: str,
        secret: str | None = None,
        timeout: float = 10.0,
        extra_headers: dict[str, str] | None = None,
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
    ) -> Any: ...
    def sink_ws(
        self,
        *,
        url: str,
        extra_headers: dict[str, str] | None = None,
        timeout: float = 10.0,
        payload_property: str | None = None,
        result_property: str = "ws_publish_result",
    ) -> Any: ...


@_runtime_checkable
class _RouteSourceProtocol(_Protocol):
    """Contract: source-points (NATS/WebDAV/Mongo/FS polling)."""

    def directory_scan(
        self,
        path: str,
        pattern: str = "*",
        *,
        recursive: bool = False,
        max_files: int = 1000,
        sort_by: str = "name",
        result_property: str = "directory_scan_result",
    ) -> Any: ...
    def poll(
        self,
        source_action: str,
        *,
        payload: dict[str, Any] | None = None,
        result_property: str = "polled_data",
    ) -> Any: ...
    def to_nats_js(
        self,
        subject: str,
        *,
        nats_url: str = "nats://localhost:4222",
        headers: dict[str, str] | None = None,
        payload_property: str | None = None,
        result_property: str = "nats_js_publish_result",
    ) -> Any: ...
    @classmethod
    def from_nats_js(
        cls,
        route_id: str,
        subject: str,
        stream: str,
        durable: str,
        *,
        nats_url: str = "nats://localhost:4222",
        description: str | None = None,
    ) -> Any: ...
    @classmethod
    def from_webdav(
        cls,
        route_id: str,
        url: str,
        *,
        watch_path: str = "/",
        poll_interval_seconds: int = 60,
        file_pattern: str = "*",
        username: str | None = None,
        password: str | None = None,
        processed_marker_path: str | None = None,
        marker_dedup: bool = True,
        description: str | None = None,
    ) -> Any: ...
    @classmethod
    def from_nats(
        cls,
        route_id: str,
        subject: str,
        *,
        nats_url: str = "nats://localhost:4222",
        description: str | None = None,
    ) -> Any: ...
    @classmethod
    def from_mongo(
        cls,
        route_id: str,
        connection_url: str,
        database: str,
        collection: str = "",
        *,
        full_document_lookup: bool = False,
        pipeline: list[dict[str, Any]] | None = None,
        description: str | None = None,
    ) -> Any: ...


@_runtime_checkable
class _RouteTemplateProtocol(_Protocol):
    """Contract: Jinja2-шаблоны (sync + async DSL processors)."""

    def jinja_template(
        self,
        template_string: str,
        *,
        context_from: str = "body",
        result_property: str = "rendered",
    ) -> Any: ...
    def jinja_template_file(
        self,
        path: str,
        *,
        context_from: str = "body",
        result_property: str = "rendered",
    ) -> Any: ...
    def html_template(
        self,
        template: str,
        *,
        to: str = "body.html",
        context_from: str = "body",
        autoescape: bool = True,
    ) -> Any: ...
    def pdf_template(
        self,
        template: str,
        *,
        to: str = "body.pdf_bytes",
        page_size: str = "A4",
        font_size: int = 12,
    ) -> Any: ...
    def register_filter(self, name: str, fn: Any) -> Any: ...
    def template_render_str(
        self, template_str: str, context: dict[str, Any] | None = None
    ) -> str: ...
    def render_file(
        self, template_path: str, context: dict[str, Any] | None = None
    ) -> str: ...


@_runtime_checkable
class _RouteIntegrationCoreProtocol(_Protocol):
    """Contract: action dispatch + invoke + to_route + util (call_function/get_setting/validate_response)."""

    def dispatch_action(
        self,
        action: str,
        *,
        payload_factory: Any | None = None,
        result_property: str = "action_result",
    ) -> Any: ...
    def invoke(
        self,
        action: str,
        *,
        mode: str = "sync",
        payload_factory: Any | None = None,
        reply_channel: str | None = None,
        result_property: str = "invoke_result",
        invocation_id_property: str = "invocation_id",
        timeout: float | None = None,
        correlation_id: str | None = None,
    ) -> Any: ...
    def to_route(
        self, route_id: str, *, result_property: str = "sub_result"
    ) -> Any: ...
    def call_function(
        self,
        ref: str,
        *,
        payload_from: str = "body",
        result_property: str = "function_result",
        inject: list[str] | None = None,
    ) -> Any: ...
    def get_setting(
        self, path: str, *, to: str = "body.setting", default: Any = None
    ) -> Any: ...
    def validate_response(
        self,
        *,
        schema: Any | None = None,
        on_error: str = "fail",
        source: str = "out_body",
    ) -> Any: ...
    def facade_get_health(self, name: str, *, to: str = "body.health") -> Any: ...


@_runtime_checkable
class _RouteAIOpsProtocol(_Protocol):
    """Contract: AI/ML операции (LLM/RAG/inference/structured)."""

    def llm_structured(
        self,
        *,
        model: str,
        output_schema: Any,
        prompt: str,
        retry: int = 3,
        temperature: float = 0.0,
        cost_budget_usd: float | None = None,
        to: str = "body.llm_result",
        name: str | None = None,
    ) -> Any: ...
    def ml_predict(
        self,
        model: str,
        *,
        input_field: str = "body.features",
        output_property: str = "ml_prediction",
        model_type: str | None = None,
        name: str | None = None,
    ) -> Any: ...
    def call_llm(
        self, *, prompt: str, model: str | None = None, to: str = "body.llm_result"
    ) -> Any: ...
    def parse_llm_output(self, schema: Any | None = None) -> Any: ...
    def token_budget(self, max_tokens: int = 4096) -> Any: ...
    def llm_fallback(self, *models: str) -> Any: ...
    def rag_search(
        self, query: str, *, top_k: int = 5, to: str = "body.rag_hits"
    ) -> Any: ...
    def rag_query(
        self, query: str, *, top_k: int = 5, to: str = "body.rag_result"
    ) -> Any: ...


@_runtime_checkable
class _RouteWorkflowOpsProtocol(_Protocol):
    """Contract: Temporal workflow orchestration (invoke/cancel/sub/schedule/audit)."""

    def invoke_workflow(
        self,
        name: str,
        *,
        mode: str = "async-api",
        args: dict[str, Any] | None = None,
        namespace: str = "default",
        task_queue: str = "default",
        result_property: str = "workflow_result",
        invocation_id_property: str = "invocation_id",
        reply_timeout_seconds: float = 60.0,
        version: str | None = None,
    ) -> Any: ...
    def cancel_workflow(
        self,
        workflow_id: str,
        *,
        reason: str = "",
        namespace: str = "default",
        result_property: str = "cancel_result",
    ) -> Any: ...
    def sub_workflow(
        self,
        name: str,
        args: dict[str, Any],
        *,
        namespace: str = "default",
        task_queue: str = "default",
        sub_workflow_id_property: str = "sub_workflow_id",
        result_property: str = "sub_workflow_result",
        parent_workflow_id_property: str = "workflow_id",
        parent_correlation_id_property: str = "correlation_id",
    ) -> Any: ...
    def cron_schedule(
        self,
        name: str,
        *,
        cron_expr: str,
        workflow_name: str,
        workflow_args: dict[str, Any] | None = None,
        namespace: str = "default",
        task_queue: str = "default",
        result_property: str = "schedule_handle",
        timezone: str = "UTC",
    ) -> Any: ...
    def audit(
        self,
        *,
        action: str | None = None,
        action_from: str | None = None,
        actor: str = "system",
        actor_from: str | None = None,
        resource_from: str | None = None,
        outcome: str = "success",
        outcome_from: str | None = None,
        metadata_from: str | None = None,
        tenant_id_from: str | None = None,
        correlation_id_from: str | None = None,
        result_property: str = "audit_event_hash",
    ) -> Any: ...


@_runtime_checkable
class _RouteAgentProtocol(_Protocol):
    """Contract: agent DSL (graph/memory/skills/branch/loop/parallel)."""

    def agent_graph(self, *, nodes: list[Any], edges: list[Any], entry: str) -> Any: ...
    def skill_invoke(
        self, skill: str, *, args: dict[str, Any] | None = None
    ) -> Any: ...
    def ai_memory_recall(
        self, query: str, *, top_k: int = 5, to: str = "body.memory_recall"
    ) -> Any: ...
    def ai_memory_store(
        self, *, key: str | None = None, value: Any | None = None
    ) -> Any: ...
    def ai_invoke(
        self,
        skill: str,
        *,
        args: dict[str, Any] | None = None,
        result_property: str = "ai_result",
    ) -> Any: ...
    def agent_branch(
        self, when: Any, _then_procs: list[Any], _else_procs: list[Any]
    ) -> Any: ...
    def agent_loop(
        self,
        processors: list[Any],
        *,
        until: Any | None = None,
        max_iterations: int = 10,
    ) -> Any: ...
    def agent_parallel(
        self, branches: dict[str, list[Any]], *, strategy: str = "all"
    ) -> Any: ...


@_runtime_checkable
class _RouteConverterProtocol(_Protocol):
    """Contract: format converters (to_*/from_* — JSON/CSV/XML/YAML/Excel/etc)."""

    def to_json(self, *, indent: int | None = None) -> Any: ...
    def from_json(self, *, from_property: str = "body") -> Any: ...
    def to_csv(self, *, headers: list[str] | None = None) -> Any: ...
    def from_csv(self, csv_string: str | None = None) -> Any: ...
    def to_xml(self, *, root_tag: str = "root") -> Any: ...
    def from_xml(self, xml_string: str | None = None) -> Any: ...
    def to_yaml(self) -> Any: ...
    def from_yaml(self, yaml_string: str | None = None) -> Any: ...
    def to_excel(self, *, sheet_name: str = "Sheet1") -> Any: ...
    def from_excel(self, excel_bytes: bytes | None = None) -> Any: ...
    def to_parquet(self, *, compression: str = "snappy") -> Any: ...
    def from_parquet(self, parquet_bytes: bytes | None = None) -> Any: ...


@_runtime_checkable
class _RouteContentProtocol(_Protocol):
    """Contract: EIP content operations (enrich/wire_tap/multicast/recipient_list/filter/transform)."""

    def enrich(
        self,
        action: str,
        *,
        payload_factory: Any | None = None,
        result_property: str = "enrichment",
    ) -> Any: ...
    def wire_tap(self, tap_processors: list[Any]) -> Any: ...
    def multicast(
        self,
        branches: list[list[Any]],
        *,
        strategy: str = "all",
        stop_on_error: bool = False,
    ) -> Any: ...
    def recipient_list(
        self, recipients_expression: Any, *, parallel: bool = True
    ) -> Any: ...
    def content_filter(self, predicate: Any) -> Any: ...
    def content_transform(self, expression: str) -> Any: ...


@_runtime_checkable
class _RouteCollectionProtocol(_Protocol):
    """Contract: Groovy-style collection ops (9 pure-static helpers)."""

    @staticmethod
    def collect(items: Any, field: str | None = None) -> list[Any]: ...
    @staticmethod
    def find_all(
        items: Any,
        predicate: Any | None = None,
        *,
        field: str | None = None,
        value: Any = None,
    ) -> list[Any]: ...
    @staticmethod
    def find(
        items: Any,
        predicate: Any | None = None,
        *,
        field: str | None = None,
        value: Any = None,
    ) -> Any: ...
    @staticmethod
    def group_by(items: Any, field: str) -> dict[Any, list[Any]]: ...
    @staticmethod
    def sort(
        items: Any, field: str | None = None, *, reverse: bool = False
    ) -> list[Any]: ...
    @staticmethod
    def each(items: Any, action: Any) -> list[Any]: ...
    @staticmethod
    def flatten(items: Any, levels: int = 1) -> list[Any]: ...
    @staticmethod
    def unique(items: Any, field: str | None = None) -> list[Any]: ...
    @staticmethod
    def plus(items: Any, other: Any) -> list[Any]: ...


@_runtime_checkable
class _RouteSecurityProtocol(_Protocol):
    """Contract: auth / authn / webhook signing / PII masking."""

    def auth(
        self,
        methods: list[str] | str = "api_key",
        *,
        result_property: str = "auth",
        required: bool = True,
    ) -> Any: ...
    def require_header(self, name: str) -> Any: ...
    def require_bearer(self) -> Any: ...
    def require_auth(self) -> Any: ...
    def require_fields(self, *names: str) -> Any: ...
    def jwt_sign(
        self,
        *,
        secret_key: str,
        algorithm: str = "HS256",
        expires_in_seconds: int | None = 3600,
        output_property: str = "jwt",
    ) -> Any: ...
    def jwt_verify(
        self,
        *,
        secret_key: str,
        algorithm: str = "HS256",
        header: str = "Authorization",
        output_property: str = "jwt_claims",
    ) -> Any: ...
    def webhook_sign(
        self,
        *,
        secret: str,
        header: str = "X-Webhook-Signature",
        algorithm: str = "sha256",
    ) -> Any: ...


@_runtime_checkable
class _RouteConfigProtocol(_Protocol):
    """Contract: per-step modifiers (with_*) + route-level overrides."""

    def with_timeout(self, seconds: float) -> Any: ...
    def with_retries(
        self, max_attempts: int, *, backoff: str | float | None = None
    ) -> Any: ...
    def with_circuit_breaker(
        self, name: str, *, failure_threshold: int = 5, recovery_timeout: float = 30.0
    ) -> Any: ...
    def with_headers(self, headers: dict[str, str], *, mode: str = "merge") -> Any: ...
    def with_auth(
        self,
        *,
        token: str | None = None,
        api_key: str | None = None,
        mtls_cert: str | None = None,
    ) -> Any: ...
    def set_header(self, key: str, value: Any) -> Any: ...
    def with_pool_size(self, n: int) -> Any: ...
    def with_max_message_size(self, bytes_: int) -> Any: ...
    def with_message_timeout(self, seconds: float) -> Any: ...
    def with_connection_pool(
        self, min_size: int = 2, max_size: int = 20, timeout: float = 5.0
    ) -> Any: ...
    def with_reconnection(
        self, max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0
    ) -> Any: ...
