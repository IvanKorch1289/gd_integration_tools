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
    """Установить override для ``action_bus_service`` provider (test-инжекция)."""
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
    module = _importlib_import_module(
        "src.backend.services.execution.action_dispatcher"
    )
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
    """Установить override для ``scheduler_manager`` provider (test-инжекция)."""
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
    """Установить override для ``workflow_event_store`` provider (test-инжекция)."""
    _overrides["workflow_event_store"] = cls


def get_workflow_state_store_provider() -> Any:
    """Возвращает класс ``WorkflowInstanceStore`` (без инстанцирования)."""
    if "workflow_state_store" in _overrides:
        return _overrides["workflow_state_store"]
    module = resolve_module("workflow.pg_runner_internals")
    return module.WorkflowInstanceStore


def set_workflow_state_store_provider(cls: Any) -> None:
    """Установить override для ``workflow_state_store`` provider (test-инжекция)."""
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
    """Установить override для ``workflow_main_session`` provider (test-инжекция)."""
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
    """Установить override для ``resilience_coordinator`` provider (test-инжекция)."""
    _overrides["resilience_coordinator"] = coordinator


def get_resilience_components_report_provider() -> Any:
    """Возвращает callable ``resilience_components_report`` для health/components."""
    if "resilience_components_report" in _overrides:
        return _overrides["resilience_components_report"]
    module = resolve_module("resilience.health")
    return module.resilience_components_report


def set_resilience_components_report_provider(callable_: Any) -> None:
    """Установить override для ``resilience_components_report`` provider (test-инжекция)."""
    _overrides["resilience_components_report"] = callable_


# ─────────────── Rate limiter (webhook handler) ───────────────


def get_rate_limiter_provider() -> Any:
    """Возвращает singleton ``RedisRateLimiter`` (см. ``RateLimiterProtocol``)."""
    if "rate_limiter" in _overrides:
        return _overrides["rate_limiter"]
    module = resolve_module("resilience.unified_rate_limiter")
    return module.get_rate_limiter()


def set_rate_limiter_provider(limiter: Any) -> None:
    """Установить override для ``rate_limiter`` provider (test-инжекция)."""
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
    """Установить override для ``app_logger`` provider (test-инжекция)."""
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
    """Установить override для ``correlation_context_setter`` provider (test-инжекция)."""
    _overrides["correlation_context_setter"] = setter


def get_grpc_logger_provider() -> Any:
    """Возвращает ``grpc_logger`` из ``logging_service``."""
    if "grpc_logger" in _overrides:
        return _overrides["grpc_logger"]
    module = resolve_module("external_apis.logging_service")
    return module.grpc_logger


def set_grpc_logger_provider(logger: Any) -> None:
    """Установить override для ``grpc_logger`` provider (test-инжекция)."""
    _overrides["grpc_logger"] = logger


def get_stream_logger_provider() -> Any:
    """Возвращает ``stream_logger`` из ``logging_service``."""
    if "stream_logger" in _overrides:
        return _overrides["stream_logger"]
    module = resolve_module("external_apis.logging_service")
    return module.stream_logger


def set_stream_logger_provider(logger: Any) -> None:
    """Установить override для ``stream_logger`` provider (test-инжекция)."""
    _overrides["stream_logger"] = logger


# ─────────────── Stream DLQ writer (cycle-5/D-AUDIT-504) ───────────────
#
# MQ subscribers (``entrypoints/stream/subscribers.py``,
# ``entrypoints/stream/invoker_subscribers.py``) используют
# ``get_stream_dlq_writer_provider()`` для enqueue poison message в
# DLQ при exception в handler (B-17 fail-loud pattern).
#
# Composition root (``plugins/composition/di.py``) ОБЯЗАН вызвать
# ``set_stream_dlq_writer_provider(writer)`` после wiring'a
# :class:`InboxDLQWriter` — иначе MQ poison-message теряются
# (silent fallback с warning-логом).


def get_stream_dlq_writer_provider() -> Any:
    """Возвращает ``DLQWriter`` для MQ subscribers.

    Returns:
        ``None`` если composition root не установил writer — MQ handlers
        log warning и drop poison message (fail-loud signal).

    """
    return _overrides.get("stream_dlq_writer")


def set_stream_dlq_writer_provider(writer: Any) -> None:
    """Установить override для ``stream_dlq_writer`` provider (test-инжекция)."""
    _overrides["stream_dlq_writer"] = writer


__all__ = (
    "get_action_bus_service_provider",
    "get_action_dispatcher_provider",
    "get_app_logger_provider",
    "get_correlation_context_setter_provider",
    "get_grpc_logger_provider",
    "get_notifications_module_provider",
    "get_rate_limit_classes_provider",
    "get_rate_limiter_provider",
    "get_resilience_components_report_provider",
    "get_resilience_coordinator_provider",
    "get_scheduler_manager_provider",
    "get_stream_dlq_writer_provider",
    "get_stream_logger_provider",
    "get_workflow_backend_factory_provider",
    "get_workflow_event_store_provider",
    "get_workflow_factory_module_provider",
    "get_workflow_instance_model_provider",
    "get_workflow_main_session_provider",
    "get_workflow_state_repository_provider",
    "get_workflow_state_row_class_provider",
    "get_workflow_state_store_provider",
    "get_workflow_status_enum_provider",
    "set_action_bus_service_provider",
    "set_action_dispatcher_provider",
    "set_app_logger_provider",
    "set_correlation_context_setter_provider",
    "set_grpc_logger_provider",
    "set_notifications_module_provider",
    "set_rate_limiter_provider",
    "set_resilience_components_report_provider",
    "set_resilience_coordinator_provider",
    "set_scheduler_manager_provider",
    "set_stream_dlq_writer_provider",
    "set_stream_logger_provider",
    "set_workflow_backend_factory_provider",
    "set_workflow_event_store_provider",
    "set_workflow_factory_module_provider",
    "set_workflow_main_session_provider",
    "set_workflow_state_repository_provider",
    "set_workflow_state_store_provider",
)


# ─── S69 M2-#11 batch 4: workflow backend factory provider ──────────


def get_workflow_backend_factory_provider() -> Any:
    r"""Возвращает :func:\`create_workflow_backend\` factory.

    S69 M2-#11 batch 4: lazy resolve для dsl/processors/sub_workflow.py.
    Был inline: ``from src.backend.infrastructure.workflow.factory import
    create_workflow_backend`` (lazy inside method body).

    Использует lazy resolve_module — НЕ тянет workflow factory при import.
    """
    if "workflow_backend_factory" in _overrides:
        return _overrides["workflow_backend_factory"]
    module = resolve_module("workflow.factory")
    return module.create_workflow_backend


def set_workflow_backend_factory_provider(factory: Any) -> None:
    """Test-override для workflow backend factory (Sprint 69+)."""
    _overrides["workflow_backend_factory"] = factory


# ─── S81 M2-#11 batch 16: WorkflowStateRepository provider ──────────


def get_workflow_state_repository_provider() -> Any:
    r"""Возвращает :class:\`WorkflowStateRepository\` (saga state repo).

    S81 M2-#11 batch 16: lazy resolve для dsl/processors/saga_lra.py.
    """
    if "workflow_state_repository" in _overrides:
        return _overrides["workflow_state_repository"]
    module = resolve_module("workflow.saga_state")
    return module.WorkflowStateRepository


def set_workflow_state_repository_provider(repo: Any) -> None:
    """Test-override для WorkflowStateRepository (Sprint 81+)."""
    _overrides["workflow_state_repository"] = repo


# ─── W9 P2-13 Phase 2: workflow_factory_module + notifications_module ──────────


def get_workflow_factory_module_provider() -> Any:
    r"""Возвращает \`workflow.factory\` module alias.

    S87 (legacy): lazy resolve для workflow_subprocess.py.
    R1 fix (S95 PROGRESS_LEDGER): ключ в INFRA_MODULES = ``workflow.factory``,
    а не ``workflow`` (последний отсутствует — 45 ключей без него).
    W9 P2-13 Phase 2: перенесено из cache.py → workflow.py (canonical).
    """
    if "workflow_factory_module" in _overrides:
        return _overrides["workflow_factory_module"]
    return resolve_module("workflow.factory")  # R1 fix: ключ + нет .factory suffix


def set_workflow_factory_module_provider(module: Any) -> None:
    """Test-override (S87+, W9 P2-13 Phase 2)."""
    _overrides["workflow_factory_module"] = module


def get_notifications_module_provider() -> Any:
    r"""Возвращает \`notifications\` module (notification channels).

    S87 (legacy): lazy resolve для notify/__init__.py.
    W9 P2-13 Phase 2: перенесено из cache.py → workflow.py (notifications = workflow concern).
    """
    if "notifications_module" in _overrides:
        return _overrides["notifications_module"]
    module = resolve_module("notifications")
    return module


def set_notifications_module_provider(module: Any) -> None:
    """Test-override (S87+, W9 P2-13 Phase 2)."""
    _overrides["notifications_module"] = module


# ─── W9 P2-13 Phase 2: sinks + DLQ + reply_channel providers (migrated from cache.py) ──────────


def get_reply_channel_class_provider() -> Any:
    r"""Возвращает :class:\`ReplyChannel\` class (singleton via \`instance()\`).

    S73 M2-#11 batch 8: lazy resolve для dsl/processors/request_reply.py.
    ReplyChannel — class с classmethod \`instance()\` (singleton).
    Caller делает \`ReplyChannel.instance()\` для получения singleton.

    W9 P2-13 Phase 2: перенесено из cache.py → workflow.py (messaging = workflow).
    """
    if "reply_channel_class" in _overrides:
        return _overrides["reply_channel_class"]
    module = resolve_module("clients.messaging.reply_channel")
    return module.ReplyChannel


def set_reply_channel_class_provider(channel_class: Any) -> None:
    """Test-override для ReplyChannel class (Sprint 73+, W9 P2-13 Phase 2)."""
    _overrides["reply_channel_class"] = channel_class


def get_sink_factory_provider() -> Any:
    r"""Возвращает \`build_sink\` (sink factory).

    S87 (legacy): lazy resolve для sink_publish/generic.py.
    W9 P2-13 Phase 2: перенесено из cache.py → workflow.py.
    """
    if "sink_factory" in _overrides:
        return _overrides["sink_factory"]
    module = resolve_module("sinks.factory")
    return module.build_sink


def set_sink_factory_provider(factory: Any) -> None:
    """Test-override (S87+, W9 P2-13 Phase 2)."""
    _overrides["sink_factory"] = factory


def get_mq_sink_class_provider() -> Any:
    r"""Возвращает :class:\`MqSink\` (messaging queue sink).

    S87 (legacy): lazy resolve для sink_publish/messaging.py.
    W9 P2-13 Phase 2: перенесено из cache.py → workflow.py.
    """
    if "mq_sink_class" in _overrides:
        return _overrides["mq_sink_class"]
    module = resolve_module("sinks.mq_sink")
    return module.MqSink


def set_mq_sink_class_provider(aclass: Any) -> None:
    """Test-override (S87+, W9 P2-13 Phase 2)."""
    _overrides["mq_sink_class"] = aclass


def get_ws_sink_class_provider() -> Any:
    r"""Возвращает :class:\`WsSink\` (WebSocket sink).

    S87 (legacy): lazy resolve для sink_publish/messaging.py.
    W9 P2-13 Phase 2: перенесено из cache.py → workflow.py.
    """
    if "ws_sink_class" in _overrides:
        return _overrides["ws_sink_class"]
    module = resolve_module("sinks.ws_sink")
    return module.WsSink


def set_ws_sink_class_provider(aclass: Any) -> None:
    """Test-override (S87+, W9 P2-13 Phase 2)."""
    _overrides["ws_sink_class"] = aclass


def get_grpc_sink_class_provider() -> Any:
    r"""Возвращает :class:\`GrpcSink\` (gRPC sink).

    S87 (legacy): lazy resolve для sink_publish/protocols.py.
    W9 P2-13 Phase 2: перенесено из cache.py → workflow.py.
    """
    if "grpc_sink_class" in _overrides:
        return _overrides["grpc_sink_class"]
    module = resolve_module("sinks.grpc_sink")
    return module.GrpcSink


def set_grpc_sink_class_provider(aclass: Any) -> None:
    """Test-override (S87+, W9 P2-13 Phase 2)."""
    _overrides["grpc_sink_class"] = aclass


def get_soap_sink_class_provider() -> Any:
    r"""Возвращает :class:\`SoapSink\` (SOAP sink).

    S87 (legacy): lazy resolve для sink_publish/protocols.py.
    W9 P2-13 Phase 2: перенесено из cache.py → workflow.py.
    """
    if "soap_sink_class" in _overrides:
        return _overrides["soap_sink_class"]
    module = resolve_module("sinks.soap_sink")
    return module.SoapSink


def set_soap_sink_class_provider(aclass: Any) -> None:
    """Test-override (S87+, W9 P2-13 Phase 2)."""
    _overrides["soap_sink_class"] = aclass


# ─── W9 P2-13 Phase 2: DLQ providers (migrated from cache.py) ──────────


def get_di_bridge_dlq_module_provider() -> Any:
    r"""Возвращает \`di_bridge.dlq\` module (SAGA DLQ bridge).

    S87 final batch (legacy): lazy resolve для security/pii_erase.py.
    W9 P2-13 Phase 2: перенесено из cache.py → workflow.py.
    """
    if "di_bridge_dlq" in _overrides:
        return _overrides["di_bridge_dlq"]
    module = resolve_module("di_bridge.dlq")
    return module


def set_di_bridge_dlq_module_provider(module: Any) -> None:
    """Test-override (S87+, W9 P2-13 Phase 2)."""
    _overrides["di_bridge_dlq"] = module


def get_dlq_memory_writer_module_provider() -> Any:
    r"""Возвращает \`messaging.dlq.memory_writer\` module (in-memory DLQ).

    S87 final batch (legacy): lazy resolve для security/pii_erase.py.
    W9 P2-13 Phase 2: перенесено из cache.py → workflow.py.
    """
    if "dlq_memory_writer" in _overrides:
        return _overrides["dlq_memory_writer"]
    module = resolve_module("messaging.dlq.memory_writer")
    return module


def set_dlq_memory_writer_module_provider(module: Any) -> None:
    """Test-override (S87+, W9 P2-13 Phase 2)."""
    _overrides["dlq_memory_writer"] = module


def get_dlq_envelope_class_provider() -> Any:
    r"""Возвращает \`di_bridge.dlq\` module (DLQEnvelope/DLQReason accessors).

    S87 final batch (legacy): lazy resolve для security/pii_erase.py. Модуль
    предоставляет ``get_dlq_envelope_class()`` / ``get_dlq_reason_class()``
    (атрибута ``DLQEnvelope`` в di_bridge.dlq нет — только accessor-функции).
    W9 P2-13 Phase 2: перенесено из cache.py → workflow.py.
    """
    if "dlq_envelope_class" in _overrides:
        return _overrides["dlq_envelope_class"]
    module = resolve_module("di_bridge.dlq")
    return module


def set_dlq_envelope_class_provider(aclass: Any) -> None:
    """Test-override (S87+, W9 P2-13 Phase 2)."""
    _overrides["dlq_envelope_class"] = aclass
