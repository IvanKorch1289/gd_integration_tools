"""Workflow providers subpackage (W9 P2-13 Phase 7).

W9 P2-13 Phase 7 (cycle 153, MINIMAX plan): извлечено из
``core/di/providers/workflow.py`` (602 LOC god-module) в package с 6 cohesion
submodules (см. ADR-0331).

Back-compat: ``core/di/providers/workflow.py`` (singular, файл) → thin re-export shim.
``core/di/providers/__init__.py`` (public API) без изменений.

Public API (all 58 funcs доступны через обе entry points):
    from src.backend.core.di.providers.workflow import (
        get_action_bus_service_provider, set_action_bus_service_provider,
        get_action_dispatcher_provider, set_action_dispatcher_provider,
        get_scheduler_manager_provider, set_scheduler_manager_provider,
        get_workflow_event_store_provider, set_workflow_event_store_provider,
        get_workflow_state_store_provider, set_workflow_state_store_provider,
        get_workflow_state_row_class_provider,
        get_workflow_main_session_provider, set_workflow_main_session_provider,
        get_workflow_instance_model_provider,
        get_workflow_status_enum_provider,
        get_workflow_backend_factory_provider, set_workflow_backend_factory_provider,
        get_workflow_state_repository_provider, set_workflow_state_repository_provider,
        get_workflow_factory_module_provider, set_workflow_factory_module_provider,
        get_notifications_module_provider, set_notifications_module_provider,
        get_resilience_coordinator_provider, set_resilience_coordinator_provider,
        get_resilience_components_report_provider, set_resilience_components_report_provider,
        get_rate_limiter_provider, set_rate_limiter_provider,
        get_rate_limit_classes_provider,
        get_app_logger_provider, set_app_logger_provider,
        get_correlation_context_setter_provider, set_correlation_context_setter_provider,
        get_grpc_logger_provider, set_grpc_logger_provider,
        get_stream_logger_provider, set_stream_logger_provider,
        get_stream_dlq_writer_provider, set_stream_dlq_writer_provider,
        get_reply_channel_class_provider, set_reply_channel_class_provider,
        get_sink_factory_provider, set_sink_factory_provider,
        get_mq_sink_class_provider, set_mq_sink_class_provider,
        get_ws_sink_class_provider, set_ws_sink_class_provider,
        get_grpc_sink_class_provider, set_grpc_sink_class_provider,
        get_soap_sink_class_provider, set_soap_sink_class_provider,
        get_di_bridge_dlq_module_provider, set_di_bridge_dlq_module_provider,
        get_dlq_memory_writer_module_provider, set_dlq_memory_writer_module_provider,
        get_dlq_envelope_class_provider, set_dlq_envelope_class_provider,
    )

Submodules:
    _workflow_core.py — action_bus, dispatcher, scheduler, event/state_store,
                       row_class, instance_model, status_enum,
                       workflow_backend_factory, workflow_state_repository (13 funcs)
    _resilience.py — resilience_coordinator, components_report,
                     rate_limiter, rate_limit_classes (5 funcs)
    _loggers.py — app_logger, correlation_setter, grpc_logger, stream_logger (5 funcs)
    _messaging.py — reply_channel_class, sink_factory, mq/ws/grpc/soap_sink_class (11 funcs)
    _dlq.py — stream_dlq_writer, di_bridge_dlq_module, dlq_memory_writer_module,
             dlq_envelope_class (7 funcs)
    _notifications.py — workflow_factory_module, notifications_module (4 funcs)
"""

from __future__ import annotations

from src.backend.core.di.providers.workflow._dlq import (
    get_di_bridge_dlq_module_provider as get_di_bridge_dlq_module_provider,
)
from src.backend.core.di.providers.workflow._dlq import (
    get_dlq_envelope_class_provider as get_dlq_envelope_class_provider,
)
from src.backend.core.di.providers.workflow._dlq import (
    get_dlq_memory_writer_module_provider as get_dlq_memory_writer_module_provider,
)
from src.backend.core.di.providers.workflow._dlq import (
    get_stream_dlq_writer_provider as get_stream_dlq_writer_provider,
)
from src.backend.core.di.providers.workflow._dlq import (
    set_di_bridge_dlq_module_provider as set_di_bridge_dlq_module_provider,
)
from src.backend.core.di.providers.workflow._dlq import (
    set_dlq_envelope_class_provider as set_dlq_envelope_class_provider,
)
from src.backend.core.di.providers.workflow._dlq import (
    set_dlq_memory_writer_module_provider as set_dlq_memory_writer_module_provider,
)
from src.backend.core.di.providers.workflow._dlq import (
    set_stream_dlq_writer_provider as set_stream_dlq_writer_provider,
)
from src.backend.core.di.providers.workflow._loggers import (
    get_app_logger_provider as get_app_logger_provider,
)
from src.backend.core.di.providers.workflow._loggers import (
    get_correlation_context_setter_provider as get_correlation_context_setter_provider,
)
from src.backend.core.di.providers.workflow._loggers import (
    get_grpc_logger_provider as get_grpc_logger_provider,
)
from src.backend.core.di.providers.workflow._loggers import (
    get_stream_logger_provider as get_stream_logger_provider,
)
from src.backend.core.di.providers.workflow._loggers import (
    set_app_logger_provider as set_app_logger_provider,
)
from src.backend.core.di.providers.workflow._loggers import (
    set_correlation_context_setter_provider as set_correlation_context_setter_provider,
)
from src.backend.core.di.providers.workflow._loggers import (
    set_grpc_logger_provider as set_grpc_logger_provider,
)
from src.backend.core.di.providers.workflow._loggers import (
    set_stream_logger_provider as set_stream_logger_provider,
)
from src.backend.core.di.providers.workflow._messaging import (
    get_grpc_sink_class_provider as get_grpc_sink_class_provider,
)
from src.backend.core.di.providers.workflow._messaging import (
    get_mq_sink_class_provider as get_mq_sink_class_provider,
)
from src.backend.core.di.providers.workflow._messaging import (
    get_reply_channel_class_provider as get_reply_channel_class_provider,
)
from src.backend.core.di.providers.workflow._messaging import (
    get_sink_factory_provider as get_sink_factory_provider,
)
from src.backend.core.di.providers.workflow._messaging import (
    get_soap_sink_class_provider as get_soap_sink_class_provider,
)
from src.backend.core.di.providers.workflow._messaging import (
    get_ws_sink_class_provider as get_ws_sink_class_provider,
)
from src.backend.core.di.providers.workflow._messaging import (
    set_grpc_sink_class_provider as set_grpc_sink_class_provider,
)
from src.backend.core.di.providers.workflow._messaging import (
    set_mq_sink_class_provider as set_mq_sink_class_provider,
)
from src.backend.core.di.providers.workflow._messaging import (
    set_reply_channel_class_provider as set_reply_channel_class_provider,
)
from src.backend.core.di.providers.workflow._messaging import (
    set_sink_factory_provider as set_sink_factory_provider,
)
from src.backend.core.di.providers.workflow._messaging import (
    set_soap_sink_class_provider as set_soap_sink_class_provider,
)
from src.backend.core.di.providers.workflow._messaging import (
    set_ws_sink_class_provider as set_ws_sink_class_provider,
)
from src.backend.core.di.providers.workflow._notifications import (
    get_notifications_module_provider as get_notifications_module_provider,
)
from src.backend.core.di.providers.workflow._notifications import (
    get_workflow_factory_module_provider as get_workflow_factory_module_provider,
)
from src.backend.core.di.providers.workflow._notifications import (
    set_notifications_module_provider as set_notifications_module_provider,
)
from src.backend.core.di.providers.workflow._notifications import (
    set_workflow_factory_module_provider as set_workflow_factory_module_provider,
)
from src.backend.core.di.providers.workflow._overrides_store import (
    _overrides as _overrides,
)
from src.backend.core.di.providers.workflow._resilience import (
    get_rate_limit_classes_provider as get_rate_limit_classes_provider,
)
from src.backend.core.di.providers.workflow._resilience import (
    get_rate_limiter_provider as get_rate_limiter_provider,
)
from src.backend.core.di.providers.workflow._resilience import (
    get_resilience_components_report_provider as get_resilience_components_report_provider,
)
from src.backend.core.di.providers.workflow._resilience import (
    get_resilience_coordinator_provider as get_resilience_coordinator_provider,
)
from src.backend.core.di.providers.workflow._resilience import (
    set_rate_limiter_provider as set_rate_limiter_provider,
)
from src.backend.core.di.providers.workflow._resilience import (
    set_resilience_components_report_provider as set_resilience_components_report_provider,
)
from src.backend.core.di.providers.workflow._resilience import (
    set_resilience_coordinator_provider as set_resilience_coordinator_provider,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    get_action_bus_service_provider as get_action_bus_service_provider,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    get_action_dispatcher_provider as get_action_dispatcher_provider,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    get_scheduler_manager_provider as get_scheduler_manager_provider,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    get_workflow_backend_factory_provider as get_workflow_backend_factory_provider,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    get_workflow_event_store_provider as get_workflow_event_store_provider,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    get_workflow_instance_model_provider as get_workflow_instance_model_provider,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    get_workflow_main_session_provider as get_workflow_main_session_provider,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    get_workflow_state_repository_provider as get_workflow_state_repository_provider,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    get_workflow_state_row_class_provider as get_workflow_state_row_class_provider,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    get_workflow_state_store_provider as get_workflow_state_store_provider,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    get_workflow_status_enum_provider as get_workflow_status_enum_provider,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    set_action_bus_service_provider as set_action_bus_service_provider,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    set_action_dispatcher_provider as set_action_dispatcher_provider,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    set_scheduler_manager_provider as set_scheduler_manager_provider,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    set_workflow_backend_factory_provider as set_workflow_backend_factory_provider,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    set_workflow_event_store_provider as set_workflow_event_store_provider,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    set_workflow_main_session_provider as set_workflow_main_session_provider,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    set_workflow_state_repository_provider as set_workflow_state_repository_provider,
)
from src.backend.core.di.providers.workflow._workflow_core import (
    set_workflow_state_store_provider as set_workflow_state_store_provider,
)
