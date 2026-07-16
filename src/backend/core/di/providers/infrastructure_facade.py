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
    "get_workflow_builder_class",
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


# --- Remaining accessors (domains without a dedicated bridge) ----------------
# These cover database, AI, event_bus, workflow, scheduler, repositories,
# jupyter_hub, storage clients, security, caching, RAG cache. They are kept
# inline to preserve the exact public surface until a follow-up wave extracts
# their own bridge modules.

def get_external_db_registry() -> Any:
    """Возвращает ``database.database.accessors.get_external_db_registry``."""
    from src.backend.infrastructure.database.database.accessors import (
        get_external_db_registry,
    )

    return get_external_db_registry


def get_prompt_cache_middleware() -> Any:
    """Возвращает ``ai.prompt_cache_middleware`` module."""
    from src.backend.infrastructure.ai import prompt_cache_middleware

    return prompt_cache_middleware


def get_abstract_repository_class() -> Any:
    """Возвращает ``repositories.base.AbstractRepository`` class."""
    from src.backend.infrastructure.repositories.base import AbstractRepository

    return AbstractRepository


def get_jupyter_hub_client_class() -> Any:
    """Возвращает ``clients.external.jupyter_hub.JupyterHubClient`` class."""
    from src.backend.infrastructure.clients.external.jupyter_hub import JupyterHubClient

    return JupyterHubClient


def get_jupyter_hub_error_class() -> Any:
    """Возвращает ``clients.external.jupyter_hub.JupyterHubError`` exception."""
    from src.backend.infrastructure.clients.external.jupyter_hub import JupyterHubError

    return JupyterHubError


def get_jupyter_hub_server_class() -> Any:
    """Возвращает ``clients.external.jupyter_hub.JupyterHubServer`` class."""
    from src.backend.infrastructure.clients.external.jupyter_hub import JupyterHubServer

    return JupyterHubServer


def get_jupyter_hub_user_class() -> Any:
    """Возвращает ``clients.external.jupyter_hub.JupyterHubUser`` class."""
    from src.backend.infrastructure.clients.external.jupyter_hub import JupyterHubUser

    return JupyterHubUser


def get_main_session_manager_factory() -> Any:
    """Возвращает ``database.session_manager.main_session_manager`` singleton."""
    from src.backend.infrastructure.database.session_manager import main_session_manager

    return main_session_manager


def get_main_session_manager_getter() -> Any:
    """Возвращает ``database.session_manager.get_main_session_manager`` factory."""
    from src.backend.infrastructure.database.session_manager import get_main_session_manager

    return get_main_session_manager


def get_event_bus_class() -> Any:
    """Возвращает ``messaging.event_bus.EventBus`` class."""
    from src.backend.infrastructure.clients.messaging.event_bus import EventBus

    return EventBus


def get_event_schema_validation_error_class() -> Any:
    """Возвращает ``messaging.event_bus.EventSchemaValidationError`` class."""
    from src.backend.infrastructure.clients.messaging.event_bus import EventSchemaValidationError

    return EventSchemaValidationError


def get_flag_event_class() -> Any:
    """Возвращает ``messaging.event_bus.FlagEvent`` class."""
    from src.backend.infrastructure.clients.messaging.event_bus import FlagEvent

    return FlagEvent


def get_generic_event_class() -> Any:
    """Возвращает ``messaging.event_bus.GenericEvent`` class."""
    from src.backend.infrastructure.clients.messaging.event_bus import GenericEvent

    return GenericEvent


def get_order_event_class() -> Any:
    """Возвращает ``messaging.event_bus.OrderEvent`` class."""
    from src.backend.infrastructure.clients.messaging.event_bus import OrderEvent

    return OrderEvent


def get_pipeline_event_class() -> Any:
    """Возвращает ``messaging.event_bus.PipelineEvent`` class."""
    from src.backend.infrastructure.clients.messaging.event_bus import PipelineEvent

    return PipelineEvent


def get_route_event_class() -> Any:
    """Возвращает ``messaging.event_bus.RouteEvent`` class."""
    from src.backend.infrastructure.clients.messaging.event_bus import RouteEvent

    return RouteEvent


def get_event_bus_factory() -> Any:
    """Возвращает ``messaging.event_bus.get_event_bus`` factory."""
    from src.backend.infrastructure.clients.messaging.event_bus import get_event_bus

    return get_event_bus


def get_workflow_builder_class() -> Any:
    """Возвращает ``workflow.builder.WorkflowBuilder`` class."""
    from src.backend.infrastructure.workflow.builder import WorkflowBuilder

    return WorkflowBuilder


def get_dsl_step_executor_class() -> Any:
    """Возвращает ``workflow.executor.DSLStepExecutor`` class."""
    from src.backend.infrastructure.workflow.executor import DSLStepExecutor

    return DSLStepExecutor


def get_durable_workflow_processor_class() -> Any:
    """Возвращает ``workflow.executor.DurableWorkflowProcessor`` class."""
    from src.backend.infrastructure.workflow.executor import DurableWorkflowProcessor

    return DurableWorkflowProcessor


def get_workflow_spec_class() -> Any:
    """Возвращает ``workflow.executor.WorkflowSpec`` class."""
    from src.backend.infrastructure.workflow.executor import WorkflowSpec

    return WorkflowSpec


def get_workflow_step_class() -> Any:
    """Возвращает ``workflow.executor.WorkflowStep`` class."""
    from src.backend.infrastructure.workflow.executor import WorkflowStep

    return WorkflowStep


def get_db_initializer_factory() -> Any:
    """Возвращает ``database.session_manager.get_db_initializer`` factory."""
    from src.backend.infrastructure.database.session_manager import get_db_initializer

    return get_db_initializer


def get_three_tier_rag_cache_class() -> Any:
    """Возвращает ``cache.rag.three_tier.ThreeTierRagCache`` class."""
    from src.backend.infrastructure.cache.rag.three_tier import ThreeTierRagCache

    return ThreeTierRagCache


def get_redis_client_class() -> Any:
    """Возвращает ``clients.storage.redis.RedisClient`` class."""
    from src.backend.infrastructure.clients.storage.redis import RedisClient

    return RedisClient


def get_e2b_sandbox_class() -> Any:
    """Возвращает ``ai.e2b_sandbox.E2BSandbox`` class."""
    from src.backend.infrastructure.ai.e2b_sandbox import E2BSandbox

    return E2BSandbox


def get_sqlalchemy_repository_class() -> Any:
    """Возвращает ``repositories.base.SQLAlchemyRepository`` class."""
    from src.backend.infrastructure.repositories.base import SQLAlchemyRepository

    return SQLAlchemyRepository


def get_repository_for_model_factory() -> Any:
    """Возвращает ``repositories.base.get_repository_for_model`` factory."""
    from src.backend.infrastructure.repositories.base import get_repository_for_model

    return get_repository_for_model


def get_redis_client_factory() -> Any:
    """Возвращает ``clients.storage.redis.get_redis_client`` factory.

    Implementation: dynamic module-attr lookup через ``__getattr__`` style
    (PEP 562) — позволяет monkeypatch'ить ``get_redis_client`` в tests
    через ``monkeypatch.setattr(module, "get_redis_client", ...)``.
    """
    import src.backend.infrastructure.clients.storage.redis as _redis_mod
    return _redis_mod.get_redis_client


def get_caching_decorator_class() -> Any:
    """Возвращает ``decorators.caching.decorator.CachingDecorator`` class."""
    from src.backend.infrastructure.decorators.caching.decorator import CachingDecorator

    return CachingDecorator


def get_dsl_variables_helper() -> Any:
    """Возвращает ``database.models.dsl_variables`` helper."""
    from src.backend.infrastructure.database.models import dsl_variables

    return dsl_variables


def get_scheduler_manager_class() -> Any:
    """Возвращает ``scheduler.scheduler_manager.SchedulerManager`` class."""
    from src.backend.infrastructure.scheduler.scheduler_manager import SchedulerManager

    return SchedulerManager


def get_scheduler_manager_factory() -> Any:
    """Возвращает ``scheduler.scheduler_manager.get_scheduler_manager`` factory."""
    from src.backend.infrastructure.scheduler.scheduler_manager import get_scheduler_manager

    return get_scheduler_manager


def get_caching_decorator_module() -> Any:
    """Возвращает ``decorators.caching.decorator`` module."""
    from src.backend.infrastructure.decorators.caching import decorator as _mod
    return _mod


def get_inject_openai_prompt_cache() -> Any:
    """Возвращает ``ai.prompt_cache_middleware.inject_openai_prompt_cache``."""
    from src.backend.infrastructure.ai.prompt_cache_middleware import (
        inject_openai_prompt_cache,
    )

    return inject_openai_prompt_cache


def get_inject_prompt_cache() -> Any:
    """Возвращает ``ai.prompt_cache_middleware.inject_prompt_cache``."""
    from src.backend.infrastructure.ai.prompt_cache_middleware import (
        inject_prompt_cache,
    )

    return inject_prompt_cache


def get_env_aes_gcm_key_provider_class() -> Any:
    """Возвращает ``security.token_registry.EnvAESGCMKeyProvider`` class."""
    from src.backend.infrastructure.security.token_registry import EnvAESGCMKeyProvider

    return EnvAESGCMKeyProvider


def get_redis_token_registry_class() -> Any:
    """Возвращает ``security.token_registry.RedisTokenRegistry`` class."""
    from src.backend.infrastructure.security.token_registry import RedisTokenRegistry

    return RedisTokenRegistry


def get_env_aesgcm_key_provider_class() -> Any:
    """Возвращает ``security.token_registry.EnvAESGCMKeyProvider`` class."""
    from src.backend.infrastructure.security.token_registry import EnvAESGCMKeyProvider

    return EnvAESGCMKeyProvider


def get_external_db_registry_factory() -> Any:
    """Возвращает ``database.database.accessors.get_external_db_registry`` factory."""
    from src.backend.infrastructure.database.database.accessors import get_external_db_registry

    return get_external_db_registry


def get_dsl_variables_attr(name: str) -> Any:
    """Возвращает атрибут ``database.models.<name>`` (DSL variables)."""
    from src.backend.infrastructure.database import models

    return getattr(models, name)


def get_inject_openai_prompt_cache_factory() -> Any:
    """Возвращает ``ai.prompt_cache_middleware.inject_openai_prompt_cache`` factory."""
    from src.backend.infrastructure.ai.prompt_cache_middleware import inject_openai_prompt_cache

    return inject_openai_prompt_cache


def get_inject_prompt_cache_factory() -> Any:
    """Возвращает ``ai.prompt_cache_middleware.inject_prompt_cache`` factory."""
    from src.backend.infrastructure.ai.prompt_cache_middleware import inject_prompt_cache

    return inject_prompt_cache


def get_object_storage_class() -> Any:
    """Возвращает ``storage.object_storage.ObjectStorage`` class."""
    from src.backend.infrastructure.storage.object_storage import ObjectStorage

    return ObjectStorage


def get_clickhouse_client_class() -> Any:
    """Возвращает ``clients.storage.clickhouse.ClickHouseClient`` class."""
    from src.backend.infrastructure.clients.storage.clickhouse import ClickHouseClient
    return ClickHouseClient


def get_mongodb_client_class() -> Any:
    """Возвращает ``clients.storage.mongodb.MongoDBClient`` class."""
    from src.backend.infrastructure.clients.storage.mongodb import MongoDBClient
    return MongoDBClient


def get_kafka_producer_class() -> Any:
    """Возвращает ``clients.messaging.kafka_producer.KafkaProducer`` class."""
    from src.backend.infrastructure.clients.messaging.kafka_producer import KafkaProducer
    return KafkaProducer
