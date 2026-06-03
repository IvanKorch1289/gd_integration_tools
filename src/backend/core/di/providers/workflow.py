"""Workflow domain providers — actions, scheduler, workflow storage, resilience, loggers.

T-P1.2c split: извлечено из monolithic ``providers.py`` (S38 P1 epic).
Domain scope: 30 funcs (15 get + 15 set), 0 private helpers.

Singleton cache ``_overrides`` is per-domain (NOT shared).

Includes:
- Action bus / dispatcher (services.execution layer)
- APScheduler manager
- Workflow event/state store + DB models + enums (pg_runner_internals)
- Resilience coordinator / health report
- Rate limiter + classes
- App/grpc/stream loggers
- Correlation context setter
"""

from __future__ import annotations

from importlib import import_module as _importlib_import_module
from typing import Any

from src.backend.core.di.module_registry import resolve_module

_INFRA = "src." + "backend.infrastructure"

_overrides: dict[str, Any] = {}


# ─────────────── Wave 6.5a: Action bus (entrypoints/api/generator) ───────────────


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
    module = _importlib_import_module("src.backend.services.execution.action_dispatcher")
    return module.get_action_dispatcher()


def set_action_dispatcher_provider(dispatcher: Any) -> None:
    """Подменяет ``DefaultActionDispatcher`` (для тестов).

    Передайте ``None``, чтобы сбросить override и вернуться к singleton.
    """
    if dispatcher is None:
        _overrides.pop("action_dispatcher", None)
    else:
        _overrides["action_dispatcher"] = dispatcher


# ─────────────── APScheduler manager ───────────────


def get_scheduler_manager_provider() -> Any:
    """Возвращает singleton ``SchedulerManager`` (APScheduler-обёртка)."""
    if "scheduler_manager" in _overrides:
        return _overrides["scheduler_manager"]
    module = resolve_module("scheduler.scheduler_manager")
    return module.scheduler_manager


def set_scheduler_manager_provider(manager: Any) -> None:
    _overrides["scheduler_manager"] = manager


# ─────────────── Workflow event/state stores (pg_runner_internals) ───────────────


def get_workflow_event_store_provider() -> Any:
    """Возвращает класс ``WorkflowEventStore`` (без инстанцирования).

    Реализация: ``infrastructure.workflow.pg_runner_internals.WorkflowEventStore``.
    """
    if "workflow_event_store" in _overrides:
        return _overrides["workflow_event_store"]
    module = resolve_module("workflow.pg_runner_internals")
    return module.WorkflowEventStore


def set_workflow_event_store_provider(cls: Any) -> None:
    _overrides["workflow_event_store"] = cls


def get_workflow_state_store_provider() -> Any:
    """Возвращает класс ``WorkflowInstanceStore`` (без инстанцирования)."""
    if "workflow_state_store" in _overrides:
        return _overrides["workflow_state_store"]
    module = resolve_module("workflow.pg_runner_internals")
    return module.WorkflowInstanceStore


def set_workflow_state_store_provider(cls: Any) -> None:
    _overrides["workflow_state_store"] = cls


def get_workflow_state_row_class_provider() -> Any:
    """Возвращает DTO-класс ``WorkflowInstanceRow`` (для ORM→DTO маппинга)."""
    if "workflow_state_row_class" in _overrides:
        return _overrides["workflow_state_row_class"]
    module = resolve_module("workflow.pg_runner_internals")
    return module.WorkflowInstanceRow


# ─────────────── Workflow DB session + ORM models + enums ───────────────


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


# ─────────────── Resilience coordinator / health report ───────────────


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


# ─────────────── Rate limiter (webhook handler) ───────────────


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


# ─────────────── App/grpc/stream loggers (entrypoints/middlewares) ───────────────


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


__all__ = (
    "get_action_bus_service_provider",
    "get_action_dispatcher_provider",
    "get_app_logger_provider",
    "get_correlation_context_setter_provider",
    "get_grpc_logger_provider",
    "get_rate_limit_classes_provider",
    "get_rate_limiter_provider",
    "get_resilience_components_report_provider",
    "get_resilience_coordinator_provider",
    "get_scheduler_manager_provider",
    "get_stream_logger_provider",
    "get_workflow_event_store_provider",
    "get_workflow_instance_model_provider",
    "get_workflow_main_session_provider",
    "get_workflow_state_row_class_provider",
    "get_workflow_state_store_provider",
    "get_workflow_status_enum_provider",
    "set_action_bus_service_provider",
    "set_action_dispatcher_provider",
    "set_app_logger_provider",
    "set_correlation_context_setter_provider",
    "set_grpc_logger_provider",
    "set_rate_limiter_provider",
    "set_resilience_components_report_provider",
    "set_resilience_coordinator_provider",
    "set_scheduler_manager_provider",
    "set_stream_logger_provider",
    "set_workflow_event_store_provider",
    "set_workflow_main_session_provider",
    "set_workflow_state_store_provider",
)
