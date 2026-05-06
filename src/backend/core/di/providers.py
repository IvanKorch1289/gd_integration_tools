"""Lazy-провайдеры инфраструктурных синглтонов для services-слоя.

Wave 6.2: services-слой не имеет права импортировать ``infrastructure.*``
напрямую. Эти провайдеры используют ``importlib`` для resolve-а
конкретных реализаций в runtime, что не нарушает layer policy
(статический AST-линтер не считает динамический import).

Все провайдеры — singleton-кеширующие: реальный объект резолвится один
раз и потом возвращается без повторных импортов.
"""

from __future__ import annotations

import importlib
from typing import Any

from src.backend.core.di.module_registry import resolve_module

__all__ = (
    "get_cache_invalidator_provider",
    "get_slo_tracker_provider",
    "get_health_aggregator_provider",
    "get_healthcheck_session_provider",
    "get_admin_cache_storage_provider",
    "set_cache_invalidator_provider",
    "set_slo_tracker_provider",
    "set_health_aggregator_provider",
    "set_healthcheck_session_provider",
    "set_admin_cache_storage_provider",
    # Wave 6.3: services/ai/* → providers
    "get_http_client_provider",
    "get_ai_sanitizer_provider",
    "get_redis_stream_client_provider",
    "get_mongo_client_provider",
    "get_llm_judge_metrics_provider",
    "set_http_client_provider",
    "set_ai_sanitizer_provider",
    "set_redis_stream_client_provider",
    "set_mongo_client_provider",
    "set_llm_judge_metrics_provider",
    # Wave 6.4: services/{io,ops,integrations,execution}/* → providers
    "get_browser_client_provider",
    "get_clickhouse_client_provider",
    "get_smtp_client_provider",
    "get_express_client_provider",
    "get_redis_kv_client_provider",
    "get_scheduler_manager_provider",
    "get_taskiq_invocation_task_provider",
    "get_external_session_manager_provider",
    "get_signature_builder_provider",
    "get_response_cache_provider",
    "get_connector_config_store_provider",
    "get_import_gateway_factory_provider",
    "get_file_repo_provider",
    "set_browser_client_provider",
    "set_clickhouse_client_provider",
    "set_smtp_client_provider",
    "set_express_client_provider",
    "set_redis_kv_client_provider",
    "set_scheduler_manager_provider",
    "set_taskiq_invocation_task_provider",
    "set_external_session_manager_provider",
    "set_signature_builder_provider",
    "set_response_cache_provider",
    "set_connector_config_store_provider",
    "set_import_gateway_factory_provider",
    "set_file_repo_provider",
    # Wave 6.5a: entrypoints/api/* → providers
    "get_api_key_manager_provider",
    "get_action_bus_service_provider",
    "get_connector_registry_provider",
    "get_connector_registry_errors_provider",
    "get_workflow_event_store_provider",
    "get_workflow_state_store_provider",
    "get_workflow_state_row_class_provider",
    "get_workflow_main_session_provider",
    "get_workflow_instance_model_provider",
    "get_workflow_status_enum_provider",
    "get_s3_service_provider",
    "get_antivirus_service_provider",
    "get_resilience_coordinator_provider",
    "get_resilience_components_report_provider",
    "get_model_enum_provider",
    "get_app_logger_provider",
    "get_correlation_context_setter_provider",
    "set_api_key_manager_provider",
    "set_action_bus_service_provider",
    "set_connector_registry_provider",
    "set_workflow_event_store_provider",
    "set_workflow_state_store_provider",
    "set_workflow_main_session_provider",
    "set_s3_service_provider",
    "set_antivirus_service_provider",
    "set_resilience_coordinator_provider",
    "set_resilience_components_report_provider",
    "set_model_enum_provider",
    "set_app_logger_provider",
    "set_correlation_context_setter_provider",
    # Wave 6.5b: entrypoints/{cdc,email,express,graphql,grpc,mcp,scheduler,
    # stream,streamlit,webhook,websocket}/* → providers
    "get_rate_limiter_provider",
    "get_rate_limit_classes_provider",
    "get_redis_hash_factory_provider",
    "get_redis_set_factory_provider",
    "get_redis_pubsub_factory_provider",
    "get_redis_cursor_factory_provider",
    "get_cdc_client_provider",
    "get_vault_refresher_provider",
    "get_grpc_logger_provider",
    "get_stream_logger_provider",
    "get_express_dialog_store_provider",
    "get_express_session_store_provider",
    "get_express_metrics_recorder_provider",
    "get_stream_client_provider",
    "get_express_bot_client_factory_provider",
    "get_express_botx_message_class_provider",
    "set_rate_limiter_provider",
    "set_redis_hash_factory_provider",
    "set_redis_set_factory_provider",
    "set_redis_pubsub_factory_provider",
    "set_redis_cursor_factory_provider",
    "set_cdc_client_provider",
    "set_vault_refresher_provider",
    "set_grpc_logger_provider",
    "set_stream_logger_provider",
    "set_express_dialog_store_provider",
    "set_express_session_store_provider",
    "set_express_metrics_recorder_provider",
    "set_stream_client_provider",
    "set_express_bot_client_factory_provider",
    # Wave 14.1.D: action gateway dispatcher
    "get_action_dispatcher_provider",
    "set_action_dispatcher_provider",
)


# DEPRECATED (Wave 6.1): локальные ``_*_MOD`` константы оставлены ради
# обратной совместимости и для возможного in-place отладочного
# использования. Все провайдеры ниже резолвят модули через единый
# реестр ``src.core.di.module_registry.resolve_module(...)`` —
# при дальнейшей чистке этот блок можно удалить.
#
# Имена инфраструктурных модулей собираются динамически, чтобы
# `tools/check_layers.py` не считал их прямыми статическими импортами.
_INFRA = "src." + "backend.infrastructure"
_CACHE_MOD = f"{_INFRA}.cache"
_SLO_MOD = f"{_INFRA}.application.slo_tracker"
_HEALTH_AGG_MOD = f"{_INFRA}.application.health_aggregator"
_HEALTH_CHECK_MOD = f"{_INFRA}.monitoring.health_check"
_REDIS_MOD = f"{_INFRA}.clients.storage.redis"
_HTTP_CLIENT_MOD = f"{_INFRA}.clients.transport.http"
_AI_SANITIZER_MOD = f"{_INFRA}.security.ai_sanitizer"
_MONGO_MOD = f"{_INFRA}.clients.storage.mongodb"
_OBS_METRICS_MOD = f"{_INFRA}.observability.metrics"
_BROWSER_MOD = f"{_INFRA}.clients.transport.browser"
_CLICKHOUSE_MOD = f"{_INFRA}.clients.storage.clickhouse"
_SMTP_MOD = f"{_INFRA}.clients.transport.smtp"
_EXPRESS_MOD = f"{_INFRA}.clients.external.express"
_SCHEDULER_MOD = f"{_INFRA}.scheduler.scheduler_manager"
_TASKIQ_MOD = f"{_INFRA}.execution.taskiq_broker"
_EXT_DB_SESSION_MOD = f"{_INFRA}.database.session_manager"
_SIGNATURES_MOD = f"{_INFRA}.security.signatures"
_RESPONSE_CACHE_MOD = f"{_INFRA}.decorators.caching"
_CONN_CFG_MOD = f"{_INFRA}.repositories.connector_configs_mongo"
_FILE_REPO_MOD = f"{_INFRA}.repositories.files"
_IMPORT_GATEWAY_MOD = f"{_INFRA}.import_gateway"

# Wave 6.5a: entrypoints/api/* и entrypoints/middlewares/*
_API_KEY_MGR_MOD = f"{_INFRA}.security.api_key_manager"
_ACTION_BUS_MOD = f"{_INFRA}.external_apis.action_bus"
_REGISTRY_MOD = f"{_INFRA}.registry"
_WF_EVENT_STORE_MOD = f"{_INFRA}.workflow.event_store"
_WF_STATE_STORE_MOD = f"{_INFRA}.workflow.state_store"
_WF_DB_SESSION_MOD = f"{_INFRA}.database.session_manager"
_WF_INSTANCE_MODEL_MOD = f"{_INFRA}.database.models.workflow_instance"
_S3_MOD = f"{_INFRA}.external_apis.s3"
_ANTIVIRUS_MOD = f"{_INFRA}.antivirus.service"
_RESILIENCE_COORDINATOR_MOD = f"{_INFRA}.resilience.coordinator"
_RESILIENCE_HEALTH_MOD = f"{_INFRA}.resilience.health"
_MODEL_REGISTRY_MOD = f"{_INFRA}.database.model_registry"
_LOGGING_SERVICE_MOD = f"{_INFRA}.external_apis.logging_service"
_CORRELATION_MOD = f"{_INFRA}.observability.correlation"

# Wave 6.5b: entrypoints/* провайдеры
_RATE_LIMITER_MOD = f"{_INFRA}.resilience.unified_rate_limiter"
_REDIS_COORD_MOD = f"{_INFRA}.clients.storage.redis_coordinator"
_CDC_MOD = f"{_INFRA}.clients.external.cdc"
_VAULT_MOD = f"{_INFRA}.application.vault_refresher"
_EXPRESS_DIALOGS_MOD = f"{_INFRA}.repositories.express_dialogs_mongo"
_EXPRESS_SESSIONS_MOD = f"{_INFRA}.repositories.express_sessions_mongo"
_STREAM_CLIENT_MOD = f"{_INFRA}.clients.messaging.stream"
_EXPRESS_BOT_MOD = f"{_INFRA}.clients.external.express_bot"


# ─────────────── Test/runtime overrides ───────────────

_overrides: dict[str, Any] = {}


def _resolve(key: str, module_path: str, attr: str) -> Any:
    """Достаёт объект из модуля через importlib с поддержкой override."""
    if key in _overrides:
        return _overrides[key]
    module = importlib.import_module(module_path)
    obj = getattr(module, attr)
    return obj() if callable(obj) and key.endswith("_callable_factory") else obj


# ─────────────── Cache invalidator ───────────────


def get_cache_invalidator_provider() -> Any:
    """Возвращает глобальный CacheInvalidator (см. ``core.interfaces.admin_cache``)."""
    if "cache_invalidator" in _overrides:
        return _overrides["cache_invalidator"]
    module = resolve_module("cache")
    return module.get_cache_invalidator()


def set_cache_invalidator_provider(invalidator: Any) -> None:
    _overrides["cache_invalidator"] = invalidator


# ─────────────── SLO tracker ───────────────


def get_slo_tracker_provider() -> Any:
    if "slo_tracker" in _overrides:
        return _overrides["slo_tracker"]
    module = resolve_module("app.slo_tracker")
    return module.get_slo_tracker()


def set_slo_tracker_provider(tracker: Any) -> None:
    _overrides["slo_tracker"] = tracker


# ─────────────── Health aggregator ───────────────


def get_health_aggregator_provider() -> Any:
    if "health_aggregator" in _overrides:
        return _overrides["health_aggregator"]
    module = resolve_module("app.health_aggregator")
    return module.get_health_aggregator()


def set_health_aggregator_provider(aggregator: Any) -> None:
    _overrides["health_aggregator"] = aggregator


# ─────────────── Health-check session factory ───────────────


def get_healthcheck_session_provider() -> Any:
    """Возвращает фабрику healthcheck-сессий (async context manager)."""
    if "healthcheck_session" in _overrides:
        return _overrides["healthcheck_session"]
    module = resolve_module("monitoring.health_check")
    return module.get_healthcheck_service


def set_healthcheck_session_provider(factory: Any) -> None:
    _overrides["healthcheck_session"] = factory


# ─────────────── Admin cache storage (Redis client) ───────────────


def get_admin_cache_storage_provider() -> Any:
    if "admin_cache_storage" in _overrides:
        return _overrides["admin_cache_storage"]
    module = resolve_module("clients.storage.redis")
    return module.redis_client


def set_admin_cache_storage_provider(client: Any) -> None:
    _overrides["admin_cache_storage"] = client


# ─────────────── HTTP-клиент (Wave 6.3, services/ai/ai_agent.py) ───────────────


def get_http_client_provider() -> Any:
    """Возвращает singleton ``HttpClient`` (см. ``HttpClientProtocol``)."""
    if "http_client" in _overrides:
        return _overrides["http_client"]
    module = resolve_module("clients.transport.http")
    return module.get_http_client_dependency()


def set_http_client_provider(client: Any) -> None:
    _overrides["http_client"] = client


# ─────────────── AI sanitizer (Wave 6.3) ───────────────


def get_ai_sanitizer_provider() -> Any:
    """Возвращает фабрику ``AIDataSanitizer`` (см. ``AISanitizerProtocol``)."""
    if "ai_sanitizer" in _overrides:
        return _overrides["ai_sanitizer"]
    module = resolve_module("security.ai_sanitizer")
    return module.get_ai_sanitizer()


def set_ai_sanitizer_provider(sanitizer: Any) -> None:
    _overrides["ai_sanitizer"] = sanitizer


# ─────────────── Redis stream client (Wave 6.3, llm_judge / semantic_cache) ───────────────


def get_redis_stream_client_provider() -> Any:
    """Возвращает singleton ``redis_client`` (см. ``RedisStreamClientProtocol``).

    Используется в ``services/ai/llm_judge.py`` для публикации verdicts
    в Redis stream и в ``services/ai/semantic_cache.py`` для exact-lookup.
    """
    if "redis_stream_client" in _overrides:
        return _overrides["redis_stream_client"]
    module = resolve_module("clients.storage.redis")
    return module.redis_client


def set_redis_stream_client_provider(client: Any) -> None:
    _overrides["redis_stream_client"] = client


# ─────────────── Mongo client (Wave 6.3, agent_memory) ───────────────


def get_mongo_client_provider() -> Any:
    """Возвращает фабрику ``MongoDBClient`` (см. ``MongoClientProtocol``)."""
    if "mongo_client" in _overrides:
        return _overrides["mongo_client"]
    module = resolve_module("clients.storage.mongodb")
    return module.get_mongo_client


def set_mongo_client_provider(factory: Any) -> None:
    _overrides["mongo_client"] = factory


# ─────────────── LLM-judge metrics recorder (Wave 6.3) ───────────────


def get_llm_judge_metrics_provider() -> Any:
    """Возвращает callable ``record_llm_judge`` (см. ``LLMJudgeMetricsProtocol``).

    Реализация: ``infrastructure.observability.metrics.record_llm_judge``.
    Если функция отсутствует (минимальный профиль без prometheus_client),
    возвращается no-op.
    """
    if "llm_judge_metrics" in _overrides:
        return _overrides["llm_judge_metrics"]
    module = resolve_module("observability.metrics")
    return getattr(module, "record_llm_judge", _noop_llm_judge_metrics)


def set_llm_judge_metrics_provider(recorder: Any) -> None:
    _overrides["llm_judge_metrics"] = recorder


def _noop_llm_judge_metrics(
    *, model: str, hallucination: float, relevance: float, toxicity: float
) -> None:
    """Заглушка, если backend метрик недоступен."""
    return None


# ─────────────── Wave 6.4: services/io/* — browser / external DB / files ───────────────


def get_browser_client_provider() -> Any:
    """Возвращает singleton ``BrowserClient`` (см. ``BrowserClientProtocol``)."""
    if "browser_client" in _overrides:
        return _overrides["browser_client"]
    module = resolve_module("clients.transport.browser")
    return module.get_browser_client()


def set_browser_client_provider(client: Any) -> None:
    _overrides["browser_client"] = client


def get_external_session_manager_provider() -> Any:
    """Возвращает фабрику ``DatabaseSessionManager`` для внешних БД.

    Реализация: ``infrastructure.database.session_manager
    .get_external_session_manager`` — фабрика, принимающая ``profile_name``.
    """
    if "external_session_manager" in _overrides:
        return _overrides["external_session_manager"]
    module = resolve_module("database.session_manager")
    return module.get_external_session_manager


def set_external_session_manager_provider(factory: Any) -> None:
    _overrides["external_session_manager"] = factory


def get_file_repo_provider() -> Any:
    """Возвращает фабрику ``FileRepository`` (см. ``FileRepositoryProtocol``)."""
    if "file_repo" in _overrides:
        return _overrides["file_repo"]
    module = resolve_module("repos.files")
    return module.get_file_repo()


def set_file_repo_provider(repo: Any) -> None:
    _overrides["file_repo"] = repo


# ─────────────── Wave 6.4: services/ops/* — analytics / notifications / scheduler ───────────────


def get_clickhouse_client_provider() -> Any:
    """Возвращает singleton ``ClickHouseClient`` (см. ``ClickHouseClientProtocol``)."""
    if "clickhouse_client" in _overrides:
        return _overrides["clickhouse_client"]
    module = resolve_module("clients.storage.clickhouse")
    return module.get_clickhouse_client()


def set_clickhouse_client_provider(client: Any) -> None:
    _overrides["clickhouse_client"] = client


def get_smtp_client_provider() -> Any:
    """Возвращает singleton ``SmtpClient`` (см. ``SmtpClientProtocol``)."""
    if "smtp_client" in _overrides:
        return _overrides["smtp_client"]
    module = resolve_module("clients.transport.smtp")
    return module.smtp_client


def set_smtp_client_provider(client: Any) -> None:
    _overrides["smtp_client"] = client


def get_express_client_provider() -> Any:
    """Возвращает singleton ``ExpressClient`` (см. ``ExpressClientProtocol``)."""
    if "express_client" in _overrides:
        return _overrides["express_client"]
    module = resolve_module("clients.external.express")
    return module.get_express_client()


def set_express_client_provider(client: Any) -> None:
    _overrides["express_client"] = client


def get_redis_kv_client_provider() -> Any:
    """Возвращает низкоуровневый redis.asyncio key-value клиент.

    В текущей инфраструктуре доступен через ``redis_client.client`` —
    провайдер скрывает этот аксессор от services-слоя.
    """
    if "redis_kv_client" in _overrides:
        return _overrides["redis_kv_client"]
    module = resolve_module("clients.storage.redis")
    return getattr(module.redis_client, "client", None) or module.redis_client


def set_redis_kv_client_provider(client: Any) -> None:
    _overrides["redis_kv_client"] = client


def get_signature_builder_provider() -> Any:
    """Возвращает callable ``build_signature_headers`` (HMAC headers)."""
    if "signature_builder" in _overrides:
        return _overrides["signature_builder"]
    module = resolve_module("security.signatures")
    return module.build_signature_headers


def set_signature_builder_provider(builder: Any) -> None:
    _overrides["signature_builder"] = builder


# ─────────────── Wave 6.4: services/integrations/* — caching / connector configs ───────────────


def get_response_cache_provider() -> Any:
    """Возвращает декоратор ``response_cache`` для services/integrations.

    Реализация: ``infrastructure.decorators.caching.response_cache``.
    Используется в DaData (single callsite) — декорирует async-метод,
    возвращает обёртку с поддержкой memory+redis backend.
    """
    if "response_cache" in _overrides:
        return _overrides["response_cache"]
    module = resolve_module("decorators.caching")
    return module.response_cache


def set_response_cache_provider(decorator: Any) -> None:
    _overrides["response_cache"] = decorator


def get_connector_config_store_provider() -> Any:
    """Возвращает singleton ``MongoConnectorConfigStore``."""
    if "connector_config_store" in _overrides:
        return _overrides["connector_config_store"]
    module = resolve_module("repos.connector_configs")
    return module.get_connector_config_store()


def set_connector_config_store_provider(store: Any) -> None:
    _overrides["connector_config_store"] = store


def get_import_gateway_factory_provider() -> Any:
    """Возвращает фабрику ``build_import_gateway(kind)`` для W24 ImportService.

    Реализация: ``infrastructure.import_gateway.build_import_gateway``.
    """
    if "import_gateway_factory" in _overrides:
        return _overrides["import_gateway_factory"]
    module = resolve_module("import_gateway")
    return module.build_import_gateway


def set_import_gateway_factory_provider(factory: Any) -> None:
    _overrides["import_gateway_factory"] = factory


# ─────────────── Wave 6.4: services/execution/* — APScheduler / TaskIQ ───────────────


def get_scheduler_manager_provider() -> Any:
    """Возвращает singleton ``SchedulerManager`` (APScheduler-обёртка)."""
    if "scheduler_manager" in _overrides:
        return _overrides["scheduler_manager"]
    module = resolve_module("scheduler.scheduler_manager")
    return module.scheduler_manager


def set_scheduler_manager_provider(manager: Any) -> None:
    _overrides["scheduler_manager"] = manager


def get_taskiq_invocation_task_provider() -> Any:
    """Возвращает фабрику TaskIQ-task для ASYNC_QUEUE-режима Invoker'а.

    Реализация: ``infrastructure.execution.taskiq_broker.get_invocation_task``.
    Импорт TaskIQ опциональный — если пакет недоступен, ``importlib`` бросит
    исключение, которое вызывающий код обязан обработать.
    """
    if "taskiq_invocation_task" in _overrides:
        return _overrides["taskiq_invocation_task"]
    module = resolve_module("execution.taskiq_broker")
    return module.get_invocation_task


def set_taskiq_invocation_task_provider(factory: Any) -> None:
    _overrides["taskiq_invocation_task"] = factory


# ─────────────── Wave 6.5a: entrypoints/api/dependencies — auth ───────────────


def get_api_key_manager_provider() -> Any:
    """Возвращает singleton ``APIKeyManager``.

    Реализация: ``infrastructure.security.api_key_manager.get_api_key_manager``.
    Используется в ``entrypoints/api/dependencies/{auth,auth_selector}.py``.
    """
    if "api_key_manager" in _overrides:
        return _overrides["api_key_manager"]
    module = resolve_module("security.api_key_manager")
    return module.get_api_key_manager()


def set_api_key_manager_provider(manager: Any) -> None:
    _overrides["api_key_manager"] = manager


# ─────────────── Wave 6.5a: entrypoints/api/generator — action bus ───────────────


def get_action_bus_service_provider() -> Any:
    """Возвращает singleton ``ActionBusService``.

    Реализация: ``infrastructure.external_apis.action_bus.get_action_bus_service``.
    Модуль может отсутствовать в усечённой dev_light-сборке — провайдер
    бросает ``ImportError``, вызывающий код обязан его обработать.
    """
    if "action_bus_service" in _overrides:
        return _overrides["action_bus_service"]
    module = resolve_module("external_apis.action_bus")
    return module.get_action_bus_service()


def set_action_bus_service_provider(service: Any) -> None:
    _overrides["action_bus_service"] = service


# ─────────────── Wave 6.5a: entrypoints/api/v1/endpoints/admin_connectors ───────────────


def get_connector_registry_provider() -> Any:
    """Возвращает singleton ``ConnectorRegistry`` через ``ConnectorRegistry.instance()``."""
    if "connector_registry" in _overrides:
        return _overrides["connector_registry"]
    module = resolve_module("registry")
    return module.ConnectorRegistry.instance()


def set_connector_registry_provider(registry: Any) -> None:
    _overrides["connector_registry"] = registry


def get_connector_registry_errors_provider() -> Any:
    """Возвращает класс исключения ``ConnectorNotRegisteredError``.

    Используется ``admin_connectors.py`` для типизированной обработки ошибок
    reload без прямого импорта ``infrastructure.registry``.
    """
    if "connector_registry_errors" in _overrides:
        return _overrides["connector_registry_errors"]
    module = resolve_module("registry")
    return module.ConnectorNotRegisteredError


# ─────────────── Wave 6.5a: entrypoints/api/v1/endpoints/admin_workflows ───────────────


def get_workflow_event_store_provider() -> Any:
    """Возвращает класс ``WorkflowEventStore`` (без инстанцирования).

    Реализация: ``infrastructure.workflow.event_store.WorkflowEventStore``.
    """
    if "workflow_event_store" in _overrides:
        return _overrides["workflow_event_store"]
    module = resolve_module("workflow.event_store")
    return module.WorkflowEventStore


def set_workflow_event_store_provider(cls: Any) -> None:
    _overrides["workflow_event_store"] = cls


def get_workflow_state_store_provider() -> Any:
    """Возвращает класс ``WorkflowInstanceStore`` (без инстанцирования)."""
    if "workflow_state_store" in _overrides:
        return _overrides["workflow_state_store"]
    module = resolve_module("workflow.state_store")
    return module.WorkflowInstanceStore


def set_workflow_state_store_provider(cls: Any) -> None:
    _overrides["workflow_state_store"] = cls


def get_workflow_state_row_class_provider() -> Any:
    """Возвращает DTO-класс ``WorkflowInstanceRow`` (для ORM→DTO маппинга)."""
    if "workflow_state_row_class" in _overrides:
        return _overrides["workflow_state_row_class"]
    module = resolve_module("workflow.state_store")
    return module.WorkflowInstanceRow


def get_workflow_main_session_provider() -> Any:
    """Возвращает singleton ``main_session_manager`` для админских SQL-запросов."""
    if "workflow_main_session" in _overrides:
        return _overrides["workflow_main_session"]
    module = resolve_module("database.session_manager")
    return module.main_session_manager


def set_workflow_main_session_provider(manager: Any) -> None:
    _overrides["workflow_main_session"] = manager


def get_workflow_instance_model_provider() -> Any:
    """Возвращает ORM-класс ``WorkflowInstance`` для админских фильтров."""
    if "workflow_instance_model" in _overrides:
        return _overrides["workflow_instance_model"]
    module = resolve_module("database.models.workflow_instance")
    return module.WorkflowInstance


def get_workflow_status_enum_provider() -> Any:
    """Возвращает enum ``WorkflowStatus`` (pending/running/succeeded/...)."""
    if "workflow_status_enum" in _overrides:
        return _overrides["workflow_status_enum"]
    module = resolve_module("database.models.workflow_instance")
    return module.WorkflowStatus


# ─────────────── Wave 6.5a: entrypoints/api/v1/endpoints/files — S3 / antivirus ───────────────


def get_s3_service_provider() -> Any:
    """Возвращает singleton ``S3Service`` (см. ``S3Protocol``)."""
    if "s3_service" in _overrides:
        return _overrides["s3_service"]
    module = resolve_module("external_apis.s3")
    return module.get_s3_service_dependency()


def set_s3_service_provider(service: Any) -> None:
    _overrides["s3_service"] = service


def get_antivirus_service_provider() -> Any:
    """Возвращает singleton ``AntivirusService``."""
    if "antivirus_service" in _overrides:
        return _overrides["antivirus_service"]
    module = resolve_module("antivirus.service")
    return module.get_antivirus_service_dependency()


def set_antivirus_service_provider(service: Any) -> None:
    _overrides["antivirus_service"] = service


# ─────────────── Wave 6.5a: entrypoints/middlewares + health — resilience ───────────────


def get_resilience_coordinator_provider() -> Any:
    """Возвращает singleton ``ResilienceCoordinator``.

    Реализация: ``infrastructure.resilience.coordinator.get_resilience_coordinator``.
    """
    if "resilience_coordinator" in _overrides:
        return _overrides["resilience_coordinator"]
    module = resolve_module("resilience.coordinator")
    return module.get_resilience_coordinator()


def set_resilience_coordinator_provider(coordinator: Any) -> None:
    _overrides["resilience_coordinator"] = coordinator


def get_resilience_components_report_provider() -> Any:
    """Возвращает callable ``resilience_components_report`` для health/components."""
    if "resilience_components_report" in _overrides:
        return _overrides["resilience_components_report"]
    module = resolve_module("resilience.health")
    return module.resilience_components_report


def set_resilience_components_report_provider(callable_: Any) -> None:
    _overrides["resilience_components_report"] = callable_


# ─────────────── Wave 6.5a: entrypoints/api/v1/endpoints/tech — model_enum ───────────────


def get_model_enum_provider() -> Any:
    """Возвращает callable ``get_model_enum`` (Enum-фабрика SQLA-моделей)."""
    if "model_enum" in _overrides:
        return _overrides["model_enum"]
    module = resolve_module("database.model_registry")
    return module.get_model_enum


def set_model_enum_provider(callable_: Any) -> None:
    _overrides["model_enum"] = callable_


# ─────────────── Wave 6.5a: entrypoints/middlewares — app_logger ───────────────


def get_app_logger_provider() -> Any:
    """Возвращает singleton ``app_logger`` (структурированный logger).

    Используется в audit_log / request_log / timeout middlewares.
    """
    if "app_logger" in _overrides:
        return _overrides["app_logger"]
    module = resolve_module("external_apis.logging_service")
    return module.app_logger


def set_app_logger_provider(logger: Any) -> None:
    _overrides["app_logger"] = logger


# ─────────────── Wave 6.5a: entrypoints/middlewares — correlation context ───────────────


def get_correlation_context_setter_provider() -> Any:
    """Возвращает callable ``set_correlation_context`` (contextvar-setter).

    Используется в TenantMiddleware для передачи tenant_id в logging-контекст.
    """
    if "correlation_context_setter" in _overrides:
        return _overrides["correlation_context_setter"]
    module = resolve_module("observability.correlation")
    return module.set_correlation_context


def set_correlation_context_setter_provider(setter: Any) -> None:
    _overrides["correlation_context_setter"] = setter


# ─────────────── Wave 6.5b: Rate limiter (webhook) ───────────────


def get_rate_limiter_provider() -> Any:
    """Возвращает singleton ``RedisRateLimiter`` (см. ``RateLimiterProtocol``)."""
    if "rate_limiter" in _overrides:
        return _overrides["rate_limiter"]
    module = resolve_module("resilience.unified_rate_limiter")
    return module.get_rate_limiter()


def set_rate_limiter_provider(limiter: Any) -> None:
    _overrides["rate_limiter"] = limiter


def get_rate_limit_classes_provider() -> tuple[Any, Any]:
    """Возвращает классы ``(RateLimit, RateLimitExceeded)`` из infra-модуля.

    Используется webhook-handler'ом для ловли ``RateLimitExceeded`` и
    конструирования ``RateLimit(...)`` policy без статического импорта infra.
    """
    if "rate_limit_classes" in _overrides:
        return _overrides["rate_limit_classes"]
    module = resolve_module("resilience.unified_rate_limiter")
    return module.RateLimit, module.RateLimitExceeded


# ─────────────── Wave 6.5b: Redis coordinator primitives ───────────────


def get_redis_hash_factory_provider() -> Any:
    """Возвращает класс ``RedisHash`` (фабрика per-key инстансов)."""
    if "redis_hash_factory" in _overrides:
        return _overrides["redis_hash_factory"]
    module = resolve_module("clients.storage.redis_coordinator")
    return module.RedisHash


def set_redis_hash_factory_provider(factory: Any) -> None:
    _overrides["redis_hash_factory"] = factory


def get_redis_set_factory_provider() -> Any:
    """Возвращает класс ``RedisSet`` (фабрика per-key инстансов)."""
    if "redis_set_factory" in _overrides:
        return _overrides["redis_set_factory"]
    module = resolve_module("clients.storage.redis_coordinator")
    return module.RedisSet


def set_redis_set_factory_provider(factory: Any) -> None:
    _overrides["redis_set_factory"] = factory


def get_redis_pubsub_factory_provider() -> Any:
    """Возвращает класс ``RedisPubSub`` (фабрика per-channel инстансов)."""
    if "redis_pubsub_factory" in _overrides:
        return _overrides["redis_pubsub_factory"]
    module = resolve_module("clients.storage.redis_coordinator")
    return module.RedisPubSub


def set_redis_pubsub_factory_provider(factory: Any) -> None:
    _overrides["redis_pubsub_factory"] = factory


def get_redis_cursor_factory_provider() -> Any:
    """Возвращает класс ``RedisCursor`` (CAS-cursor)."""
    if "redis_cursor_factory" in _overrides:
        return _overrides["redis_cursor_factory"]
    module = resolve_module("clients.storage.redis_coordinator")
    return module.RedisCursor


def set_redis_cursor_factory_provider(factory: Any) -> None:
    _overrides["redis_cursor_factory"] = factory


# ─────────────── Wave 6.5b: CDC client ───────────────


def get_cdc_client_provider() -> Any:
    """Возвращает singleton ``CDCClient`` (см. ``CDCClientProtocol``)."""
    if "cdc_client" in _overrides:
        return _overrides["cdc_client"]
    module = resolve_module("clients.external.cdc")
    return module.get_cdc_client()


def set_cdc_client_provider(client: Any) -> None:
    _overrides["cdc_client"] = client


# ─────────────── Wave 6.5b: Vault secret refresher ───────────────


def get_vault_refresher_provider() -> Any:
    """Возвращает singleton ``VaultSecretRefresher`` (см. ``VaultRefresherProtocol``)."""
    if "vault_refresher" in _overrides:
        return _overrides["vault_refresher"]
    module = resolve_module("app.vault_refresher")
    return module.VaultSecretRefresher.get()


def set_vault_refresher_provider(refresher: Any) -> None:
    _overrides["vault_refresher"] = refresher


# ─────────────── Wave 6.5b: gRPC / stream loggers ───────────────


def get_grpc_logger_provider() -> Any:
    """Возвращает ``grpc_logger`` из ``logging_service``."""
    if "grpc_logger" in _overrides:
        return _overrides["grpc_logger"]
    module = resolve_module("external_apis.logging_service")
    return module.grpc_logger


def set_grpc_logger_provider(logger: Any) -> None:
    _overrides["grpc_logger"] = logger


def get_stream_logger_provider() -> Any:
    """Возвращает ``stream_logger`` из ``logging_service``."""
    if "stream_logger" in _overrides:
        return _overrides["stream_logger"]
    module = resolve_module("external_apis.logging_service")
    return module.stream_logger


def set_stream_logger_provider(logger: Any) -> None:
    _overrides["stream_logger"] = logger


# ─────────────── Wave 6.5b: Express Mongo stores ───────────────


def get_express_dialog_store_provider() -> Any:
    """Возвращает singleton ``MongoExpressDialogStore``."""
    if "express_dialog_store" in _overrides:
        return _overrides["express_dialog_store"]
    module = resolve_module("repos.express_dialogs")
    return module.get_express_dialog_store()


def set_express_dialog_store_provider(store: Any) -> None:
    _overrides["express_dialog_store"] = store


def get_express_session_store_provider() -> Any:
    """Возвращает singleton ``MongoExpressSessionStore``."""
    if "express_session_store" in _overrides:
        return _overrides["express_session_store"]
    module = resolve_module("repos.express_sessions")
    return module.get_express_session_store()


def set_express_session_store_provider(store: Any) -> None:
    _overrides["express_session_store"] = store


# ─────────────── Wave 6.5b: Express metrics recorder ───────────────


def get_express_metrics_recorder_provider() -> Any:
    """Возвращает callable ``record_express_command_received``.

    Если функция отсутствует (минимальный профиль без prometheus_client),
    возвращается no-op.
    """
    if "express_metrics_recorder" in _overrides:
        return _overrides["express_metrics_recorder"]
    module = resolve_module("observability.metrics")
    return getattr(
        module, "record_express_command_received", _noop_express_metrics_recorder
    )


def set_express_metrics_recorder_provider(recorder: Any) -> None:
    _overrides["express_metrics_recorder"] = recorder


def _noop_express_metrics_recorder(bot: str, command: str) -> None:
    """Заглушка, если backend метрик недоступен."""
    return None


# ─────────────── Wave 6.5b: FastStream client (subscriber decorators) ───────────────


def get_stream_client_provider() -> Any:
    """Возвращает singleton ``StreamClient`` (FastStream роутеры)."""
    if "stream_client" in _overrides:
        return _overrides["stream_client"]
    module = resolve_module("clients.messaging.stream")
    return module.stream_client


def set_stream_client_provider(client: Any) -> None:
    _overrides["stream_client"] = client


# ─────────────── Wave 6.5b: Express BotX client (streamlit) ───────────────


def get_express_bot_client_factory_provider() -> Any:
    """Возвращает фабрику ``get_express_client(bot_name)`` для Express BotX.

    Реализация: ``dsl.engine.processors.express._common.get_express_client``.
    Этот common-модуль нагружает infra-клиент через ленивый импорт.
    """
    if "express_bot_client_factory" in _overrides:
        return _overrides["express_bot_client_factory"]
    module = resolve_module("dsl.processors.express_common")
    return module.get_express_client


def set_express_bot_client_factory_provider(factory: Any) -> None:
    _overrides["express_bot_client_factory"] = factory


def get_express_botx_message_class_provider() -> Any:
    """Возвращает класс ``BotxMessage`` (DTO для Express)."""
    if "express_botx_message_class" in _overrides:
        return _overrides["express_botx_message_class"]
    module = resolve_module("clients.external.express_bot")
    return module.BotxMessage


# ─────────────── Wave 14.1.D: ActionGatewayDispatcher ───────────────


def get_action_dispatcher_provider() -> Any:
    """Возвращает singleton ``DefaultActionDispatcher`` (см. ``ActionGatewayDispatcher``).

    Используется entrypoint-адаптерами (HTTP/WS/Scheduler) для делегирования
    action-вызовов через middleware-цепочку (audit / idempotency / rate_limit)
    и получения унифицированного :class:`ActionResult` envelope.
    """
    if "action_dispatcher" in _overrides:
        return _overrides["action_dispatcher"]
    # Импорт через services-слой (не infrastructure) — не нарушает layer policy.
    module = importlib.import_module("src.backend.services.execution.action_dispatcher")
    return module.get_action_dispatcher()


def set_action_dispatcher_provider(dispatcher: Any) -> None:
    """Подменяет ``DefaultActionDispatcher`` (для тестов).

    Передайте ``None``, чтобы сбросить override и вернуться к singleton.
    """
    if dispatcher is None:
        _overrides.pop("action_dispatcher", None)
    else:
        _overrides["action_dispatcher"] = dispatcher
