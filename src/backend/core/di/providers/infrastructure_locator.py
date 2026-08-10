"""Infrastructure Locator — service locator for DI wiring (S31 Task 5).

.. important::
    **This is a service locator, NOT a capability-checked facade.**
    Unlike :class:`StorageFacade`, :class:`AuthFacade`, or
    :class:`EventBusFacade`, this module does NOT enforce capabilities,
    tenancy isolation, or backend-agnostic semantics. It is a thin
    convenience layer for DI wiring (lazy import + singleton access).

    Extensions and business code should prefer the domain facades in
    ``core.cache.facade``, ``core.auth.facade``, ``core.messaging.eventbus.facade``,
    ``core.audit.facade``, and ``services.storage.facade``. This locator
    is appropriate only for composition roots (FastAPI lifespan, CLI bootstrap)
    and DSL processor wiring.

Renamed from ``infrastructure_facade.py`` in cycle 31 (S31 Task 5) to clarify
architectural role. The old name was misleading — it suggested this was a
facade layer like :class:`StorageFacade`, when in fact it's a service
locator with 90+ getters returning concrete infrastructure classes as
``Any`` (no Protocol enforcement).

Decomposed from the original monolithic 856-LOC file (S171) into 6 focused
bridge modules. This file remains the single import surface; all 51 import
sites and monkeypatch string paths (``infrastructure_locator.get_X`` or the
back-compat shim ``infrastructure_facade.get_X``) keep working unchanged.

Re-exported from bridge modules:
    * ``observability_bridge`` — correlation, client_metrics, metrics_registry,
      prometheus exporters, logging
    * ``resilience_bridge``   — bulkhead, profile_store, rate limiter
    * ``dlq_bridge``          — DLQEnvelope/Reason/Writer/base module
    * ``health_bridge``       — HealthResult/Mode, InfrastructureClient,
      health_check factory, pool health
    * ``search_bridge``       — WebSearchService + tavily/searxng/perplexity
    * ``cdc_bridge``          — CDC adapters + debezium/poll/listen-notify backends

Retained inline (domains without a dedicated bridge yet):
    database, AI (prompt cache, e2b), event_bus, workflow, scheduler,
    repositories, jupyter_hub, storage clients (redis/clickhouse/mongo/kafka/
    object_storage), security (token registry), caching decorators, RAG cache.

Lazy imports inside functions (preserves import-time isolation): infrastructure
modules are not loaded until first call of a provider.
"""

# Registry-backed getters are materialized below via ``globals()`` mutation
# in the S224 loop. Ruff's F822 (undefined name in __all__) can't see those
# runtime-created names lexically. This is the standard pattern for
# meta-programming in API-façade modules.

from __future__ import annotations

import importlib as _importlib
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # ``_PROVIDERS_REGISTRY`` materializes these names at runtime.  Keep the
    # static facade contract explicit so callers do not depend on ``Any``
    # module attributes while preserving lazy imports.
    get_abstract_repository_class: Callable[[], Any]
    get_caching_decorator_class: Callable[[], Any]
    get_caching_decorator_module: Callable[[], Any]
    get_clickhouse_client_class: Callable[[], Any]
    get_db_initializer_factory: Callable[[], Any]
    get_dsl_step_executor_class: Callable[[], Any]
    get_dsl_variables_helper: Callable[[], Any]
    get_durable_workflow_processor_class: Callable[[], Any]
    get_e2b_sandbox_class: Callable[[], Any]
    get_elasticsearch_client_class: Callable[[], Any]
    get_env_aes_gcm_key_provider_class: Callable[[], Any]
    get_env_aesgcm_key_provider_class: Callable[[], Any]
    get_event_bus_class: Callable[[], Any]
    get_event_bus_factory: Callable[[], Any]
    get_event_schema_validation_error_class: Callable[[], Any]
    get_external_db_registry: Callable[[], Any]
    get_external_db_registry_factory: Callable[[], Any]
    get_flag_event_class: Callable[[], Any]
    get_generic_event_class: Callable[[], Any]
    get_inject_openai_prompt_cache: Callable[[], Any]
    get_inject_openai_prompt_cache_factory: Callable[[], Any]
    get_inject_prompt_cache: Callable[[], Any]
    get_inject_prompt_cache_factory: Callable[[], Any]
    get_jupyter_hub_client_class: Callable[[], Any]
    get_jupyter_hub_error_class: Callable[[], Any]
    get_jupyter_hub_server_class: Callable[[], Any]
    get_jupyter_hub_user_class: Callable[[], Any]
    get_kafka_producer_class: Callable[[], Any]
    get_main_session_manager_factory: Callable[[], Any]
    get_main_session_manager_getter: Callable[[], Any]
    get_mongodb_client_class: Callable[[], Any]
    get_object_storage_class: Callable[[], Any]
    get_order_event_class: Callable[[], Any]
    get_pipeline_event_class: Callable[[], Any]
    get_prompt_cache_middleware: Callable[[], Any]
    get_redis_client_class: Callable[[], Any]
    get_redis_client_factory: Callable[[], Any]
    get_redis_token_registry_class: Callable[[], Any]
    get_repository_for_model_factory: Callable[[], Any]
    get_route_event_class: Callable[[], Any]
    get_scheduler_manager_class: Callable[[], Any]
    get_scheduler_manager_factory: Callable[[], Any]
    get_sqlalchemy_repository_class: Callable[[], Any]
    get_three_tier_rag_cache_class: Callable[[], Any]
    get_workflow_spec_class: Callable[[], Any]
    get_workflow_step_class: Callable[[], Any]

from src.backend.core.di.providers.cdc_bridge import (
    get_cdc_client_adapter_class,
    get_debezium_cdc_backend_class,
    get_debezium_events_cdc_backend_class,
    get_listen_notify_cdc_backend_class,
    get_poll_cdc_backend_class,
)
from src.backend.core.di.providers.dlq_bridge import (
    get_dlq_base_module,
    get_dlq_envelope_class,
    get_dlq_reason_class,
    get_dlq_writer_class,
)
from src.backend.core.di.providers.health_bridge import (
    get_health_check_factory,
    get_health_mode_class,
    get_health_result_class,
    get_infrastructure_client_class,
    get_pool_entry_class,
    get_pool_health_monitor_class,
    get_pool_monitor_factory,
)
from src.backend.core.di.providers.observability_bridge import (
    get_client_metrics,
    get_client_metrics_module,
    get_correlation_id,
    get_correlation_module,
    get_default_labels_attr,
    get_default_labels_tuple,
    get_logger_factory,
    get_logger_protocol_class,
    get_metrics_registry_class,
    get_metrics_registry_factory,
    get_metrics_registry_singleton,
    get_prometheus_exporter,
    get_prometheus_temporal_exporter_class,
    get_prometheus_temporal_exporter_factory,
    get_record_scale_event,
    get_set_task_queue_depth,
    get_set_workers_active,
)
from src.backend.core.di.providers.resilience_bridge import (
    get_bulkhead_attr,
    get_bulkhead_class,
    get_bulkhead_registry_class,
    get_in_memory_resilience_profile_store_class,
    get_profile_store_memory_class,
    get_rate_limit_class,
    get_rate_limit_exceeded_class,
    get_rate_limiter_factory,
    get_redis_rate_limiter_class,
    get_unified_rate_limiter_attr,
)
from src.backend.core.di.providers.search_bridge import (
    get_base_search_provider_class,
    get_perplexity_provider_class,
    get_search_providers_module,
    get_searxng_provider_class,
    get_tavily_provider_class,
    get_web_search_service_class,
    get_web_search_service_factory,
)


def _load_provider(module_path: str, attr: str) -> Any:
    """S224: lazy import + attribute access."""
    return getattr(
        _importlib.import_module(f"src.backend.{module_path}"),
        attr,
    )


def _make_provider_getter(name: str, module_path: str, attr: str) -> Callable[[], Any]:
    """S224: build a ``get_X()`` function from registry entry."""
    def getter() -> Any:
        """Auto-generated by S224 (infrastructure_facade registry)."""
        return _load_provider(module_path, attr)

    getter.__name__ = name
    getter.__qualname__ = name
    return getter


# S224: registry — name (without ``get_`` prefix) → (module_path, attr).
_PROVIDERS_REGISTRY: dict[str, tuple[str, str]] = {
    "abstract_repository_class": ("infrastructure.repositories.base", "AbstractRepository"),
    "clickhouse_client_class": ("infrastructure.clients.storage.clickhouse", "ClickHouseClient"),
    "dsl_step_executor_class": ("infrastructure.workflow.executor", "DSLStepExecutor"),
    "durable_workflow_processor_class": ("infrastructure.workflow.executor", "DurableWorkflowProcessor"),
    "e2b_sandbox_class": ("infrastructure.ai.e2b_sandbox", "E2BSandbox"),
    "elasticsearch_client_class": ("infrastructure.clients.storage.elasticsearch", "ElasticSearchClient"),
    "env_aes_gcm_key_provider_class": ("infrastructure.security.token_registry", "EnvAESGCMKeyProvider"),
    "env_aesgcm_key_provider_class": ("infrastructure.security.token_registry", "EnvAESGCMKeyProvider"),
    "event_bus_factory": ("infrastructure.clients.messaging.event_bus", "get_event_bus"),
    "event_bus_class": ("infrastructure.clients.messaging.event_bus", "EventBus"),
    "event_schema_validation_error_class": ("infrastructure.clients.messaging.event_bus", "EventSchemaValidationError"),
    "external_db_registry": ("infrastructure.database.database.accessors", "get_external_db_registry"),
    "external_db_registry_factory": ("infrastructure.database.database.accessors", "get_external_db_registry"),
    "db_initializer_factory": ("infrastructure.database.session_manager", "get_db_initializer"),
    "flag_event_class": ("infrastructure.clients.messaging.event_bus", "FlagEvent"),
    "generic_event_class": ("infrastructure.clients.messaging.event_bus", "GenericEvent"),
    "inject_openai_prompt_cache": ("infrastructure.ai.prompt_cache_middleware", "inject_openai_prompt_cache"),
    "inject_openai_prompt_cache_factory": ("infrastructure.ai.prompt_cache_middleware", "inject_openai_prompt_cache"),
    "inject_prompt_cache": ("infrastructure.ai.prompt_cache_middleware", "inject_prompt_cache"),
    "inject_prompt_cache_factory": ("infrastructure.ai.prompt_cache_middleware", "inject_prompt_cache"),
    "jupyter_hub_client_class": ("infrastructure.clients.external.jupyter_hub", "JupyterHubClient"),
    "jupyter_hub_error_class": ("infrastructure.clients.external.jupyter_hub", "JupyterHubError"),
    "jupyter_hub_server_class": ("infrastructure.clients.external.jupyter_hub", "JupyterHubServer"),
    "jupyter_hub_user_class": ("infrastructure.clients.external.jupyter_hub", "JupyterHubUser"),
    "kafka_producer_class": ("infrastructure.messaging", "kafka_pool_registration"),
    "main_session_manager_factory": ("infrastructure.database.session_manager", "main_session_manager"),
    "main_session_manager_getter": ("infrastructure.database.session_manager", "get_main_session_manager"),
    "mongodb_client_class": ("infrastructure.clients.storage.mongodb", "MongoDBClient"),
    "object_storage_class": ("infrastructure.storage.object_storage", "ObjectStorage"),
    "order_event_class": ("infrastructure.clients.messaging.event_bus", "OrderEvent"),
    "pipeline_event_class": ("infrastructure.clients.messaging.event_bus", "PipelineEvent"),
    "prompt_cache_middleware": ("infrastructure.ai", "prompt_cache_middleware"),
    "redis_client_class": ("infrastructure.clients.storage.redis", "RedisClient"),
    "redis_client_factory": ("infrastructure.clients.storage.redis", "get_redis_client"),
    "redis_token_registry_class": ("infrastructure.security.token_registry", "RedisTokenRegistry"),
    "repository_for_model_factory": ("infrastructure.repositories.base", "get_repository_for_model"),
    "route_event_class": ("infrastructure.clients.messaging.event_bus", "RouteEvent"),
    "scheduler_manager_class": ("infrastructure.scheduler.scheduler_manager", "SchedulerManager"),
    "scheduler_manager_factory": ("infrastructure.scheduler.scheduler_manager", "get_scheduler_manager"),
    "sqlalchemy_repository_class": ("infrastructure.repositories.base", "SQLAlchemyRepository"),
    "three_tier_rag_cache_class": ("infrastructure.cache.rag.three_tier", "ThreeTierRagCache"),
    "caching_decorator_class": ("infrastructure.decorators.caching.decorator", "CachingDecorator"),
    "caching_decorator_module": ("infrastructure.decorators.caching", "decorator"),
    "workflow_spec_class": ("infrastructure.workflow.executor", "WorkflowSpec"),
    "workflow_step_class": ("infrastructure.workflow.executor", "WorkflowStep"),
    "dsl_variables_helper": ("infrastructure.database.models", "dsl_variables"),
}


# S224: Generate get_X() functions for all registry entries.
for _prov_name, (_prov_module, _prov_attr) in _PROVIDERS_REGISTRY.items():
    globals()[f"get_{_prov_name}"] = _make_provider_getter(
        f"get_{_prov_name}", _prov_module, _prov_attr
    )
del _prov_name, _prov_module, _prov_attr


# --- Special cases (kept manual — non-standard signatures or semantics) ---


def get_event_bus_facade_provider() -> Any:
    """S205 fix: возвращает ``EventBusFacade`` instance для DSL EventBus wiring.

    Раньше ``dsl/builders/eventbus_mixin.py::_resolve_event_bus_facade``
    импортировал эту функцию, но она не существовала — facade никогда не
    резолвился, всегда срабатывал fallback на legacy
    ``core.messaging.event_bus.get_event_bus().publish()``.

    С этим провайдером canonical capability-checked ``EventBusFacade.publish``
    путь начинает работать. Без capability_check (default) — no-op для
    capability contract, поведение идентично legacy пути.
    """
    # S32 fix: canonical path now in core (Task 3); services/ is shim.
    from src.backend.core.messaging.eventbus.facade import get_event_bus_facade

    return get_event_bus_facade()


def get_dsl_variables_attr(name: str) -> Any:
    """Возвращает атрибут ``database.models.<name>`` (DSL variables)."""
    return _load_provider("infrastructure.database.models", name)


# Legacy 44 inline functions moved to _PROVIDERS_REGISTRY + auto-generation
# above. Kept for reference (deleted during S224 refactor — see git history):
# get_prompt_cache_middleware, get_abstract_repository_class,
# get_jupyter_hub_client_class, get_jupyter_hub_error_class, etc.



























# get_redis_client_factory moved to _PROVIDERS_REGISTRY (S224).


# --- Public API surface (S224 + bridge exports) -----------------------------
# Placement at the bottom keeps the runtime-generated and manual getters next
# to the explicit bridge re-exports. The export contract test verifies all
# names materialized through ``globals()``; the file-level F822 suppression
# above is limited to that statically opaque registry pattern.

__all__ = (
    "get_abstract_repository_class",
    "get_base_search_provider_class",
    "get_bulkhead_attr",
    "get_bulkhead_class",
    "get_bulkhead_registry_class",
    "get_caching_decorator_class",
    "get_caching_decorator_module",
    "get_cdc_client_adapter_class",
    "get_client_metrics",
    "get_client_metrics_module",
    "get_correlation_id",
    "get_correlation_module",
    "get_db_initializer_factory",
    "get_debezium_cdc_backend_class",
    "get_debezium_events_cdc_backend_class",
    "get_default_labels_attr",
    "get_default_labels_tuple",
    "get_dlq_base_module",
    "get_dlq_envelope_class",
    "get_dlq_reason_class",
    "get_dlq_writer_class",
    "get_dsl_step_executor_class",
    "get_dsl_variables_attr",
    "get_dsl_variables_helper",
    "get_durable_workflow_processor_class",
    "get_e2b_sandbox_class",
    "get_env_aes_gcm_key_provider_class",
    "get_env_aesgcm_key_provider_class",
    "get_event_bus_class",
    "get_event_bus_facade_provider",
    "get_event_bus_factory",
    "get_event_schema_validation_error_class",
    "get_external_db_registry",
    "get_external_db_registry_factory",
    "get_flag_event_class",
    "get_generic_event_class",
    "get_health_check_factory",
    "get_health_mode_class",
    "get_health_result_class",
    "get_in_memory_resilience_profile_store_class",
    "get_infrastructure_client_class",
    "get_inject_openai_prompt_cache",
    "get_inject_openai_prompt_cache_factory",
    "get_inject_prompt_cache",
    "get_inject_prompt_cache_factory",
    "get_jupyter_hub_client_class",
    "get_jupyter_hub_error_class",
    "get_jupyter_hub_server_class",
    "get_jupyter_hub_user_class",
    "get_listen_notify_cdc_backend_class",
    "get_logger_factory",
    "get_logger_protocol_class",
    "get_main_session_manager_factory",
    "get_main_session_manager_getter",
    "get_metrics_registry_class",
    "get_metrics_registry_factory",
    "get_metrics_registry_singleton",
    "get_order_event_class",
    "get_perplexity_provider_class",
    "get_pipeline_event_class",
    "get_poll_cdc_backend_class",
    "get_pool_entry_class",
    "get_pool_health_monitor_class",
    "get_pool_monitor_factory",
    "get_profile_store_memory_class",
    "get_prometheus_exporter",
    "get_prometheus_temporal_exporter_class",
    "get_prometheus_temporal_exporter_factory",
    "get_prompt_cache_middleware",
    "get_rate_limit_class",
    "get_rate_limit_exceeded_class",
    "get_rate_limiter_factory",
    "get_record_scale_event",
    "get_redis_client_class",
    "get_redis_client_factory",
    "get_redis_rate_limiter_class",
    "get_redis_token_registry_class",
    "get_repository_for_model_factory",
    "get_route_event_class",
    "get_scheduler_manager_class",
    "get_scheduler_manager_factory",
    "get_search_providers_module",
    "get_searxng_provider_class",
    "get_set_task_queue_depth",
    "get_set_workers_active",
    "get_sqlalchemy_repository_class",
    "get_tavily_provider_class",
    "get_three_tier_rag_cache_class",
    "get_unified_rate_limiter_attr",
    "get_web_search_service_class",
    "get_web_search_service_factory",
    "get_workflow_spec_class",
    "get_workflow_step_class",
)
