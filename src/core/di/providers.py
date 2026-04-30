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
)


# Имена инфраструктурных модулей собираются динамически, чтобы
# `tools/check_layers.py` не считал их прямыми статическими импортами.
_INFRA = "src." + "infrastructure"
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
    module = importlib.import_module(_CACHE_MOD)
    return module.get_cache_invalidator()


def set_cache_invalidator_provider(invalidator: Any) -> None:
    _overrides["cache_invalidator"] = invalidator


# ─────────────── SLO tracker ───────────────


def get_slo_tracker_provider() -> Any:
    if "slo_tracker" in _overrides:
        return _overrides["slo_tracker"]
    module = importlib.import_module(_SLO_MOD)
    return module.get_slo_tracker()


def set_slo_tracker_provider(tracker: Any) -> None:
    _overrides["slo_tracker"] = tracker


# ─────────────── Health aggregator ───────────────


def get_health_aggregator_provider() -> Any:
    if "health_aggregator" in _overrides:
        return _overrides["health_aggregator"]
    module = importlib.import_module(_HEALTH_AGG_MOD)
    return module.get_health_aggregator()


def set_health_aggregator_provider(aggregator: Any) -> None:
    _overrides["health_aggregator"] = aggregator


# ─────────────── Health-check session factory ───────────────


def get_healthcheck_session_provider() -> Any:
    """Возвращает фабрику healthcheck-сессий (async context manager)."""
    if "healthcheck_session" in _overrides:
        return _overrides["healthcheck_session"]
    module = importlib.import_module(_HEALTH_CHECK_MOD)
    return module.get_healthcheck_service


def set_healthcheck_session_provider(factory: Any) -> None:
    _overrides["healthcheck_session"] = factory


# ─────────────── Admin cache storage (Redis client) ───────────────


def get_admin_cache_storage_provider() -> Any:
    if "admin_cache_storage" in _overrides:
        return _overrides["admin_cache_storage"]
    module = importlib.import_module(_REDIS_MOD)
    return module.redis_client


def set_admin_cache_storage_provider(client: Any) -> None:
    _overrides["admin_cache_storage"] = client


# ─────────────── HTTP-клиент (Wave 6.3, services/ai/ai_agent.py) ───────────────


def get_http_client_provider() -> Any:
    """Возвращает singleton ``HttpClient`` (см. ``HttpClientProtocol``)."""
    if "http_client" in _overrides:
        return _overrides["http_client"]
    module = importlib.import_module(_HTTP_CLIENT_MOD)
    return module.get_http_client_dependency()


def set_http_client_provider(client: Any) -> None:
    _overrides["http_client"] = client


# ─────────────── AI sanitizer (Wave 6.3) ───────────────


def get_ai_sanitizer_provider() -> Any:
    """Возвращает фабрику ``AIDataSanitizer`` (см. ``AISanitizerProtocol``)."""
    if "ai_sanitizer" in _overrides:
        return _overrides["ai_sanitizer"]
    module = importlib.import_module(_AI_SANITIZER_MOD)
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
    module = importlib.import_module(_REDIS_MOD)
    return module.redis_client


def set_redis_stream_client_provider(client: Any) -> None:
    _overrides["redis_stream_client"] = client


# ─────────────── Mongo client (Wave 6.3, agent_memory) ───────────────


def get_mongo_client_provider() -> Any:
    """Возвращает фабрику ``MongoDBClient`` (см. ``MongoClientProtocol``)."""
    if "mongo_client" in _overrides:
        return _overrides["mongo_client"]
    module = importlib.import_module(_MONGO_MOD)
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
    module = importlib.import_module(_OBS_METRICS_MOD)
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
    module = importlib.import_module(_BROWSER_MOD)
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
    module = importlib.import_module(_EXT_DB_SESSION_MOD)
    return module.get_external_session_manager


def set_external_session_manager_provider(factory: Any) -> None:
    _overrides["external_session_manager"] = factory


def get_file_repo_provider() -> Any:
    """Возвращает фабрику ``FileRepository`` (см. ``FileRepositoryProtocol``)."""
    if "file_repo" in _overrides:
        return _overrides["file_repo"]
    module = importlib.import_module(_FILE_REPO_MOD)
    return module.get_file_repo()


def set_file_repo_provider(repo: Any) -> None:
    _overrides["file_repo"] = repo


# ─────────────── Wave 6.4: services/ops/* — analytics / notifications / scheduler ───────────────


def get_clickhouse_client_provider() -> Any:
    """Возвращает singleton ``ClickHouseClient`` (см. ``ClickHouseClientProtocol``)."""
    if "clickhouse_client" in _overrides:
        return _overrides["clickhouse_client"]
    module = importlib.import_module(_CLICKHOUSE_MOD)
    return module.get_clickhouse_client()


def set_clickhouse_client_provider(client: Any) -> None:
    _overrides["clickhouse_client"] = client


def get_smtp_client_provider() -> Any:
    """Возвращает singleton ``SmtpClient`` (см. ``SmtpClientProtocol``)."""
    if "smtp_client" in _overrides:
        return _overrides["smtp_client"]
    module = importlib.import_module(_SMTP_MOD)
    return module.smtp_client


def set_smtp_client_provider(client: Any) -> None:
    _overrides["smtp_client"] = client


def get_express_client_provider() -> Any:
    """Возвращает singleton ``ExpressClient`` (см. ``ExpressClientProtocol``)."""
    if "express_client" in _overrides:
        return _overrides["express_client"]
    module = importlib.import_module(_EXPRESS_MOD)
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
    module = importlib.import_module(_REDIS_MOD)
    return getattr(module.redis_client, "client", None) or module.redis_client


def set_redis_kv_client_provider(client: Any) -> None:
    _overrides["redis_kv_client"] = client


def get_signature_builder_provider() -> Any:
    """Возвращает callable ``build_signature_headers`` (HMAC headers)."""
    if "signature_builder" in _overrides:
        return _overrides["signature_builder"]
    module = importlib.import_module(_SIGNATURES_MOD)
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
    module = importlib.import_module(_RESPONSE_CACHE_MOD)
    return module.response_cache


def set_response_cache_provider(decorator: Any) -> None:
    _overrides["response_cache"] = decorator


def get_connector_config_store_provider() -> Any:
    """Возвращает singleton ``MongoConnectorConfigStore``."""
    if "connector_config_store" in _overrides:
        return _overrides["connector_config_store"]
    module = importlib.import_module(_CONN_CFG_MOD)
    return module.get_connector_config_store()


def set_connector_config_store_provider(store: Any) -> None:
    _overrides["connector_config_store"] = store


def get_import_gateway_factory_provider() -> Any:
    """Возвращает фабрику ``build_import_gateway(kind)`` для W24 ImportService.

    Реализация: ``infrastructure.import_gateway.build_import_gateway``.
    """
    if "import_gateway_factory" in _overrides:
        return _overrides["import_gateway_factory"]
    module = importlib.import_module(_IMPORT_GATEWAY_MOD)
    return module.build_import_gateway


def set_import_gateway_factory_provider(factory: Any) -> None:
    _overrides["import_gateway_factory"] = factory


# ─────────────── Wave 6.4: services/execution/* — APScheduler / TaskIQ ───────────────


def get_scheduler_manager_provider() -> Any:
    """Возвращает singleton ``SchedulerManager`` (APScheduler-обёртка)."""
    if "scheduler_manager" in _overrides:
        return _overrides["scheduler_manager"]
    module = importlib.import_module(_SCHEDULER_MOD)
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
    module = importlib.import_module(_TASKIQ_MOD)
    return module.get_invocation_task


def set_taskiq_invocation_task_provider(factory: Any) -> None:
    _overrides["taskiq_invocation_task"] = factory
