"""Backward-compat facade — bridge re-exports + remaining accessors.

Decomposed from the original monolithic 856-LOC file (S171) into 6 focused
bridge modules. This file remains the single import surface; all 51 import
sites and monkeypatch string paths (``infrastructure_facade.get_X``) keep
working unchanged.

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

from __future__ import annotations

from typing import Any

# --- Bridge re-exports (50 accessors moved to focused modules) ---------------
from src.backend.core.di.providers.observability_bridge import *  # noqa: F401,F403
from src.backend.core.di.providers.resilience_bridge import *  # noqa: F401,F403
from src.backend.core.di.providers.dlq_bridge import *  # noqa: F401,F403
from src.backend.core.di.providers.health_bridge import *  # noqa: F401,F403
from src.backend.core.di.providers.search_bridge import *  # noqa: F401,F403
from src.backend.core.di.providers.cdc_bridge import *  # noqa: F401,F403

__all__ = (
    "get_bulkhead_attr",
    "get_bulkhead_class",
    "get_bulkhead_registry_class",
    "get_caching_decorator_class",
    "get_cdc_client_adapter_class",
    "get_client_metrics",
    "get_correlation_id",
    "get_debezium_cdc_backend_class",
    "get_default_labels_tuple",
    "get_metrics_registry_class",
    "get_metrics_registry_singleton",
    "get_dlq_base_module",
    "get_metrics_registry_factory",
    "get_default_labels_attr",
    "get_dlq_writer_class",
    "get_dlq_reason_class",
    "get_correlation_module",
    "get_client_metrics_module",
    "get_inject_prompt_cache_factory",
    "get_inject_openai_prompt_cache_factory",
    "get_dsl_variables_attr",
    "get_external_db_registry_factory",
    "get_env_aesgcm_key_provider_class",
    "get_in_memory_resilience_profile_store_class",
    "get_debezium_events_cdc_backend_class",
    "get_dlq_envelope_class",
    "get_dsl_variables_helper",
    "get_env_aes_gcm_key_provider_class",
    "get_external_db_registry",
    "get_health_result_class",
    "get_health_check_factory",
    "get_infrastructure_client_class",
    "get_health_mode_class",
    "get_caching_decorator_module",
    "get_web_search_service_class",
    "get_tavily_provider_class",
    "get_searxng_provider_class",
    "get_perplexity_provider_class",
    "get_base_search_provider_class",
    "get_search_providers_module",
    "get_scheduler_manager_factory",
    "get_scheduler_manager_class",
    "get_prometheus_temporal_exporter_factory",
    "get_prometheus_temporal_exporter_class",
    "get_inject_openai_prompt_cache",
    "get_inject_prompt_cache",
    "get_listen_notify_cdc_backend_class",
    "get_poll_cdc_backend_class",
    "get_prometheus_exporter",
    "get_pool_entry_class",
    "get_pool_health_monitor_class",
    "get_pool_monitor_factory",
    "get_abstract_repository_class",
    "get_jupyter_hub_client_class",
    "get_jupyter_hub_error_class",
    "get_jupyter_hub_server_class",
    "get_jupyter_hub_user_class",
    "get_main_session_manager_factory",
    "get_main_session_manager_getter",
    "get_event_bus_class",
    "get_event_schema_validation_error_class",
    "get_flag_event_class",
    "get_generic_event_class",
    "get_order_event_class",
    "get_pipeline_event_class",
    "get_route_event_class",
    "get_event_bus_factory",
    "get_event_bus_facade_provider",
    "get_dsl_step_executor_class",
    "get_durable_workflow_processor_class",
    "get_workflow_spec_class",
    "get_workflow_step_class",
    "get_db_initializer_factory",
    "get_three_tier_rag_cache_class",
    "get_redis_client_class",
    "get_e2b_sandbox_class",
    "get_logger_protocol_class",
    "get_logger_factory",
    "get_sqlalchemy_repository_class",
    "get_repository_for_model_factory",
    "get_prompt_cache_middleware",
    "get_profile_store_memory_class",
    "get_redis_client_factory",
    "get_redis_token_registry_class",
    "get_record_scale_event",
    "get_set_task_queue_depth",
    "get_set_workers_active",
    "get_web_search_service_factory",
    "get_unified_rate_limiter_attr",
    "get_rate_limit_class",
    "get_rate_limit_exceeded_class",
    "get_redis_rate_limiter_class",
    "get_rate_limiter_factory",
)


# --- S224: Auto-generated provider accessors (44 simple getters) ----------
# Реестр ``_PROVIDERS_REGISTRY`` — single source of truth для всех
# простых get_X() функций, которые делают ``from X import Y; return Y``.
# Специальные случаи (с параметрами, разной semantic) — manual ниже.
#
# Trade-off: meta-programming vs copy-paste. 44 inline функции × 4 строки =
# 176 LOC copy-paste → 44 registry entries × 1 строка = 44 LOC + ~30 LOC
# helper code. Net: -100 LOC, +single source of truth.
#
# Ponytail guard: только простые "import + return" геттеры. Логика
# (DSL variables attr, EventBus facade, custom factories) — остаётся
# inline (clearer).

import importlib as _importlib


def _load_provider(module_path: str, attr: str) -> Any:
    """S224: lazy import + attribute access."""
    return getattr(
        _importlib.import_module(f"src.backend.{module_path}"),
        attr,
    )


def _make_provider_getter(name: str, module_path: str, attr: str):
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
    from src.backend.services.messaging.eventbus_facade import (
        get_event_bus_facade,
    )

    return get_event_bus_facade()


def get_dsl_variables_attr(name: str) -> Any:
    """Возвращает атрибут ``database.models.<name>`` (DSL variables)."""
    from src.backend.infrastructure.database import models

    return getattr(models, name)


# Legacy 44 inline functions moved to _PROVIDERS_REGISTRY + auto-generation
# above. Kept for reference (deleted during S224 refactor — see git history):
# get_prompt_cache_middleware, get_abstract_repository_class,
# get_jupyter_hub_client_class, get_jupyter_hub_error_class, etc.



























# get_redis_client_factory moved to _PROVIDERS_REGISTRY (S224).
