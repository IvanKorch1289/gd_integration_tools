"""Unified infrastructure facade через core/di/providers (Milestone 1 — isolation).

Single entry point для доменов, которые до этого были импортированы
напрямую из ``src.backend.infrastructure.*`` в core/ файлах.

Lazy imports внутри функций (preserves import-time isolation):
infrastructure modules не загружаются до первого вызова provider'а.

Доступные провайдеры:
    * ``get_correlation_id()`` — observability/correlation (re-export facade)
    * ``get_client_metrics()`` — observability/client_metrics (lazy load)
    * ``get_dlq_envelope_class()`` — DLQEnvelope class (lazy load)
    * ``get_dlq_base_module()`` — full dlq_base module (lazy load)
    * ``get_external_db_registry()`` — db accessors
    * ``get_profile_store_memory_class()`` — resilience
    * ``get_prometheus_exporter()`` — prometheus helpers
    * ``get_prompt_cache_middleware()`` — AI prompt cache
    * ``get_bulkhead_class()`` + ``get_bulkhead_registry_class()`` — resilience

Использование::

    from src.backend.core.di.providers.infrastructure_facade import (
        get_correlation_id,
        get_dlq_envelope_class,
    )

    cid = get_correlation_id()
    Envelope = get_dlq_envelope_class()
"""

from __future__ import annotations

from typing import Any

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
    "get_notifications_gateway_factory",
    "get_notification_gateway_class",
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


def get_correlation_id() -> Any:
    """Возвращает ``correlation.get_correlation_id`` function."""
    from src.backend.infrastructure.observability.correlation import get_correlation_id

    return get_correlation_id


def get_client_metrics() -> Any:
    """Возвращает ``observability.client_metrics`` module."""
    from src.backend.infrastructure.observability import client_metrics

    return client_metrics


def get_dlq_envelope_class() -> Any:
    """Возвращает ``DLQEnvelope`` class."""
    from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope

    return DLQEnvelope


def get_dlq_base_module() -> Any:
    """Возвращает ``messaging.dlq_base`` module."""
    from src.backend.infrastructure.messaging import dlq_base

    return dlq_base


def get_external_db_registry() -> Any:
    """Возвращает ``database.database.accessors.get_external_db_registry``."""
    from src.backend.infrastructure.database.database.accessors import (
        get_external_db_registry,
    )

    return get_external_db_registry


def get_profile_store_memory_class() -> Any:
    """Возвращает ``InMemoryResilienceProfileStore`` class."""
    from src.backend.infrastructure.resilience.profile_store_memory import (
        InMemoryResilienceProfileStore,
    )

    return InMemoryResilienceProfileStore


def get_prometheus_exporter() -> Any:
    """Возвращает ``observability.prometheus_temporal_exporter`` module."""
    from src.backend.infrastructure.observability import prometheus_temporal_exporter

    return prometheus_temporal_exporter


def get_prompt_cache_middleware() -> Any:
    """Возвращает ``ai.prompt_cache_middleware`` module."""
    from src.backend.infrastructure.ai import prompt_cache_middleware

    return prompt_cache_middleware


def get_bulkhead_class() -> Any:
    """Возвращает ``resilience.bulkhead.Bulkhead`` class."""
    from src.backend.infrastructure.resilience.bulkhead import Bulkhead

    return Bulkhead


def get_bulkhead_registry_class() -> Any:
    """Возвращает ``resilience.bulkhead.BulkheadRegistry`` class."""
    from src.backend.infrastructure.resilience.bulkhead import BulkheadRegistry

    return BulkheadRegistry


def get_health_result_class() -> Any:
    """Возвращает ``clients.base_connector.HealthResult`` class."""
    from src.backend.infrastructure.clients.base_connector import HealthResult

    return HealthResult


def get_default_labels_tuple() -> Any:
    """Возвращает ``observability.metrics_registry.DEFAULT_LABELS`` tuple.

    Используется в metrics consumers (services/ai/metrics.py,
    services/workflows/sla_alerting.py) для инициализации
    ``MetricsRegistry(default_labels=...)``.
    """
    from src.backend.infrastructure.observability.metrics_registry import DEFAULT_LABELS

    return DEFAULT_LABELS


def get_metrics_registry_class() -> Any:
    """Возвращает ``observability.metrics_registry.MetricsRegistry`` class."""
    from src.backend.infrastructure.observability.metrics_registry import MetricsRegistry

    return MetricsRegistry


def get_metrics_registry_singleton() -> Any:
    """Возвращает ``observability.metrics_registry.metrics_registry`` singleton."""
    from src.backend.infrastructure.observability import metrics_registry

    return metrics_registry


def get_pool_entry_class() -> Any:
    """Возвращает ``clients.pool_health.PoolEntry`` class."""
    from src.backend.infrastructure.clients.pool_health import PoolEntry

    return PoolEntry


def get_pool_health_monitor_class() -> Any:
    """Возвращает ``clients.pool_health.PoolHealthMonitor`` class."""
    from src.backend.infrastructure.clients.pool_health import PoolHealthMonitor

    return PoolHealthMonitor


def get_pool_monitor_factory() -> Any:
    """Возвращает ``clients.pool_health.get_pool_monitor`` factory."""
    from src.backend.infrastructure.clients.pool_health import get_pool_monitor

    return get_pool_monitor


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


def get_notifications_gateway_factory() -> Any:
    """Возвращает ``notifications.get_gateway`` factory."""
    from src.backend.infrastructure.notifications import get_gateway

    return get_gateway


def get_notification_gateway_class() -> Any:
    """Возвращает ``notifications.gateway.NotificationGateway`` class."""
    from src.backend.infrastructure.notifications.gateway import NotificationGateway

    return NotificationGateway


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


def get_poll_cdc_backend_class() -> Any:
    """Возвращает ``cdc.poll_backend.PollCDCBackend`` class."""
    from src.backend.infrastructure.cdc.poll_backend import PollCDCBackend

    return PollCDCBackend


def get_listen_notify_cdc_backend_class() -> Any:
    """Возвращает ``cdc.listen_notify_backend.ListenNotifyCDCBackend`` class."""
    from src.backend.infrastructure.cdc.listen_notify_backend import (
        ListenNotifyCDCBackend,
    )

    return ListenNotifyCDCBackend


def get_debezium_cdc_backend_class() -> Any:
    """Возвращает ``cdc.debezium_events_backend.DebeziumEventsCDCBackend`` class."""
    from src.backend.infrastructure.cdc.debezium_events_backend import (
        DebeziumEventsCDCBackend,
    )

    return DebeziumEventsCDCBackend


def get_cdc_client_adapter_class() -> Any:
    """Возвращает ``cdc.cdc_client_adapter.CDCClientAdapter`` class."""
    from src.backend.infrastructure.cdc.cdc_client_adapter import CDCClientAdapter

    return CDCClientAdapter


def get_dsl_variables_helper() -> Any:
    """Возвращает ``database.models.dsl_variables`` helper."""
    from src.backend.infrastructure.database.models import dsl_variables

    return dsl_variables


def get_unified_rate_limiter_attr(name: str) -> Any:
    """Возвращает атрибут из ``resilience.unified_rate_limiter``.

    Args:
        name: имя атрибута (например ``"RateLimit"``).
    """
    from src.backend.infrastructure.resilience import unified_rate_limiter

    return getattr(unified_rate_limiter, name)


def get_rate_limit_class() -> Any:
    """Возвращает ``resilience.unified_rate_limiter.RateLimit`` class."""
    from src.backend.infrastructure.resilience.unified_rate_limiter import RateLimit

    return RateLimit


def get_rate_limit_exceeded_class() -> Any:
    """Возвращает ``resilience.unified_rate_limiter.RateLimitExceeded``."""
    from src.backend.infrastructure.resilience.unified_rate_limiter import RateLimitExceeded

    return RateLimitExceeded


def get_redis_rate_limiter_class() -> Any:
    """Возвращает ``resilience.unified_rate_limiter.RedisRateLimiter`` class."""
    from src.backend.infrastructure.resilience.unified_rate_limiter import RedisRateLimiter

    return RedisRateLimiter


def get_rate_limiter_factory() -> Any:
    """Возвращает ``resilience.unified_rate_limiter.get_rate_limiter`` factory."""
    from src.backend.infrastructure.resilience.unified_rate_limiter import get_rate_limiter

    return get_rate_limiter





def get_health_check_factory() -> Any:
    """Возвращает ``clients.base_connector.get_health_check`` factory."""
    from src.backend.infrastructure.clients.base_connector import get_health_check

    return get_health_check


def get_prometheus_temporal_exporter_class() -> Any:
    """Возвращает ``observability.prometheus_temporal_exporter.PrometheusTemporalExporter`` class."""
    from src.backend.infrastructure.observability.prometheus_temporal_exporter import PrometheusTemporalExporter

    return PrometheusTemporalExporter


def get_prometheus_temporal_exporter_factory() -> Any:
    """Возвращает ``observability.prometheus_temporal_exporter.get_prometheus_temporal_exporter`` factory."""
    from src.backend.infrastructure.observability.prometheus_temporal_exporter import get_prometheus_temporal_exporter

    return get_prometheus_temporal_exporter








def get_scheduler_manager_class() -> Any:
    """Возвращает ``scheduler.scheduler_manager.SchedulerManager`` class."""
    from src.backend.infrastructure.scheduler.scheduler_manager import SchedulerManager

    return SchedulerManager


def get_scheduler_manager_factory() -> Any:
    """Возвращает ``scheduler.scheduler_manager.get_scheduler_manager`` factory."""
    from src.backend.infrastructure.scheduler.scheduler_manager import get_scheduler_manager

    return get_scheduler_manager


def get_search_providers_module() -> Any:
    """Возвращает ``clients.external.search_providers`` module."""
    from src.backend.infrastructure.clients.external import search_providers
    return search_providers


def get_base_search_provider_class() -> Any:
    """Возвращает ``clients.external.search_providers.BaseSearchProvider`` class."""
    from src.backend.infrastructure.clients.external.search_providers import BaseSearchProvider

    return BaseSearchProvider


def get_perplexity_provider_class() -> Any:
    """Возвращает ``clients.external.search_providers.PerplexityProvider`` class."""
    from src.backend.infrastructure.clients.external.search_providers import PerplexityProvider

    return PerplexityProvider


def get_searxng_provider_class() -> Any:
    """Возвращает ``clients.external.search_providers.SearXNGProvider`` class."""
    from src.backend.infrastructure.clients.external.search_providers import SearXNGProvider

    return SearXNGProvider


def get_tavily_provider_class() -> Any:
    """Возвращает ``clients.external.search_providers.TavilyProvider`` class."""
    from src.backend.infrastructure.clients.external.search_providers import TavilyProvider

    return TavilyProvider


def get_web_search_service_class() -> Any:
    """Возвращает ``clients.external.search_providers.WebSearchService`` class."""
    from src.backend.infrastructure.clients.external.search_providers import WebSearchService

    return WebSearchService


def get_caching_decorator_module() -> Any:
    """Возвращает ``decorators.caching.decorator`` module."""
    from src.backend.infrastructure.decorators.caching import decorator as _mod
    return _mod





def get_health_mode_class() -> Any:
    """Возвращает ``clients.base_connector.HealthMode`` class."""
    from src.backend.infrastructure.clients.base_connector import HealthMode

    return HealthMode


def get_infrastructure_client_class() -> Any:
    """Возвращает ``clients.base_connector.InfrastructureClient`` class."""
    from src.backend.infrastructure.clients.base_connector import InfrastructureClient

    return InfrastructureClient


def get_bulkhead_attr(name: str) -> Any:
    """Возвращает атрибут из ``resilience.bulkhead`` (Bulkhead, BulkheadRegistry).

    Args:
        name: имя атрибута.
    """
    from src.backend.infrastructure.resilience import bulkhead

    return getattr(bulkhead, name)


def get_record_scale_event() -> Any:
    """Возвращает ``observability.prometheus_temporal_exporter.record_scale_event``."""
    from src.backend.infrastructure.observability.prometheus_temporal_exporter import (
        record_scale_event,
    )

    return record_scale_event


def get_set_task_queue_depth() -> Any:
    """Возвращает ``observability.prometheus_temporal_exporter.set_task_queue_depth``."""
    from src.backend.infrastructure.observability.prometheus_temporal_exporter import (
        set_task_queue_depth,
    )

    return set_task_queue_depth


def get_set_workers_active() -> Any:
    """Возвращает ``observability.prometheus_temporal_exporter.set_workers_active``."""
    from src.backend.infrastructure.observability.prometheus_temporal_exporter import (
        set_workers_active,
    )

    return set_workers_active


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


def get_logger_protocol_class() -> Any:
    """Возвращает ``logging.base.LoggerProtocol`` class."""
    from src.backend.infrastructure.logging.base import LoggerProtocol
    return LoggerProtocol

def get_web_search_service_factory() -> Any:
    """Возвращает ``clients.external.search_providers.get_web_search_service`` factory."""
    from src.backend.infrastructure.clients.external.search_providers import get_web_search_service
    return get_web_search_service

def get_debezium_events_cdc_backend_class() -> Any:
    """Возвращает ``cdc.debezium_events_backend.DebeziumEventsCDCBackend`` class."""
    from src.backend.infrastructure.cdc.debezium_events_backend import DebeziumEventsCDCBackend

    return DebeziumEventsCDCBackend


def get_in_memory_resilience_profile_store_class() -> Any:
    """Возвращает ``resilience.profile_store_memory.InMemoryResilienceProfileStore`` class."""
    from src.backend.infrastructure.resilience.profile_store_memory import (
        InMemoryResilienceProfileStore,
    )

    return InMemoryResilienceProfileStore


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


def get_client_metrics_module() -> Any:
    """Возвращает ``observability.client_metrics`` module."""
    from src.backend.infrastructure.observability import client_metrics

    return client_metrics


def get_correlation_module() -> Any:
    """Возвращает ``observability.correlation`` module."""
    from src.backend.infrastructure.observability import correlation

    return correlation


def get_dlq_reason_class() -> Any:
    """Возвращает ``messaging.dlq_base.DLQReason`` class."""
    from src.backend.infrastructure.messaging.dlq_base import DLQReason

    return DLQReason


def get_dlq_writer_class() -> Any:
    """Возвращает ``messaging.dlq_base.DLQWriter`` class."""
    from src.backend.infrastructure.messaging.dlq_base import DLQWriter

    return DLQWriter


def get_default_labels_attr(name: str) -> Any:
    """Возвращает атрибут ``observability.metrics_registry.<name>`` (DEFAULT_LABELS)."""
    from src.backend.infrastructure.observability import metrics_registry

    return getattr(metrics_registry, name)


def get_metrics_registry_factory() -> Any:
    """Возвращает ``observability.metrics_registry.metrics_registry`` singleton."""
    from src.backend.infrastructure.observability.metrics_registry import metrics_registry

    return metrics_registry



def get_object_storage_class() -> Any:
    """Возвращает ``storage.object_storage.ObjectStorage`` class."""
    from src.backend.infrastructure.storage.object_storage import ObjectStorage

    return ObjectStorage


def get_health_check_factory() -> Any:
    """Возвращает ``application.health_aggregator.get_health_check`` factory."""
    from src.backend.infrastructure.application.health_aggregator import get_health_check

    return get_health_check

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
    try:
        from src.backend.infrastructure.clients.messaging.kafka_producer import KafkaProducer
        return KafkaProducer
    except ImportError:
        # Fallback to aiokafka-based producer if available
        try:
            from src.backend.infrastructure.clients.messaging.stream import StreamClient
            return StreamClient
        except ImportError:
            return None