"""Backward-compat shim — ``workflow`` стал package.

W9 P2-13 Phase 7 (cycle 153, MINIMAX plan): ``workflow.py`` (602 LOC god-module)
→ ``workflow/`` package с 6 cohesion submodules (см. ADR-0331). Этот модуль —
thin re-export shim для backward-compat: ``from core.di.providers.workflow
import X`` продолжает работать для всех 58 публичных функций.

Migration::

    # До (W9 P2-13 Phase 7 — still works через этот shim):
    from src.backend.core.di.providers.workflow import (
        get_action_bus_service_provider, set_action_bus_service_provider,
        get_workflow_event_store_provider, ... (58 funcs),
    )

    # После (canonical, рекомендуется для нового кода):
    from src.backend.core.di.providers.workflow import (
        get_action_bus_service_provider, ... (58 funcs),
    )
    # Тот же путь — split прозрачен для consumers.

Removal: запланирован на cycle 162 (отдельный cleanup wave после telemetry
audit consumer migration).
"""

from __future__ import annotations

from src.backend.core.di.providers.workflow import (  # type: ignore[attr-defined]
    get_action_bus_service_provider as get_action_bus_service_provider,
)
from src.backend.core.di.providers.workflow import (
    get_action_dispatcher_provider as get_action_dispatcher_provider,
)
from src.backend.core.di.providers.workflow import (
    get_app_logger_provider as get_app_logger_provider,
)
from src.backend.core.di.providers.workflow import (
    get_correlation_context_setter_provider as get_correlation_context_setter_provider,
)
from src.backend.core.di.providers.workflow import (
    get_di_bridge_dlq_module_provider as get_di_bridge_dlq_module_provider,
)
from src.backend.core.di.providers.workflow import (
    get_dlq_envelope_class_provider as get_dlq_envelope_class_provider,
)
from src.backend.core.di.providers.workflow import (
    get_dlq_memory_writer_module_provider as get_dlq_memory_writer_module_provider,
)
from src.backend.core.di.providers.workflow import (
    get_grpc_logger_provider as get_grpc_logger_provider,
)
from src.backend.core.di.providers.workflow import (
    get_grpc_sink_class_provider as get_grpc_sink_class_provider,
)
from src.backend.core.di.providers.workflow import (
    get_mq_sink_class_provider as get_mq_sink_class_provider,
)
from src.backend.core.di.providers.workflow import (
    get_notifications_module_provider as get_notifications_module_provider,
)
from src.backend.core.di.providers.workflow import (
    get_rate_limit_classes_provider as get_rate_limit_classes_provider,
)
from src.backend.core.di.providers.workflow import (
    get_rate_limiter_provider as get_rate_limiter_provider,
)
from src.backend.core.di.providers.workflow import (
    get_reply_channel_class_provider as get_reply_channel_class_provider,
)
from src.backend.core.di.providers.workflow import (
    get_resilience_components_report_provider as get_resilience_components_report_provider,
)
from src.backend.core.di.providers.workflow import (
    get_resilience_coordinator_provider as get_resilience_coordinator_provider,
)
from src.backend.core.di.providers.workflow import (
    get_scheduler_manager_provider as get_scheduler_manager_provider,
)
from src.backend.core.di.providers.workflow import (
    get_sink_factory_provider as get_sink_factory_provider,
)
from src.backend.core.di.providers.workflow import (
    get_soap_sink_class_provider as get_soap_sink_class_provider,
)
from src.backend.core.di.providers.workflow import (
    get_stream_dlq_writer_provider as get_stream_dlq_writer_provider,
)
from src.backend.core.di.providers.workflow import (
    get_stream_logger_provider as get_stream_logger_provider,
)
from src.backend.core.di.providers.workflow import (
    get_workflow_backend_factory_provider as get_workflow_backend_factory_provider,
)
from src.backend.core.di.providers.workflow import (
    get_workflow_event_store_provider as get_workflow_event_store_provider,
)
from src.backend.core.di.providers.workflow import (
    get_workflow_factory_module_provider as get_workflow_factory_module_provider,
)
from src.backend.core.di.providers.workflow import (
    get_workflow_instance_model_provider as get_workflow_instance_model_provider,
)
from src.backend.core.di.providers.workflow import (
    get_workflow_main_session_provider as get_workflow_main_session_provider,
)
from src.backend.core.di.providers.workflow import (
    get_workflow_state_repository_provider as get_workflow_state_repository_provider,
)
from src.backend.core.di.providers.workflow import (
    get_workflow_state_row_class_provider as get_workflow_state_row_class_provider,
)
from src.backend.core.di.providers.workflow import (
    get_workflow_state_store_provider as get_workflow_state_store_provider,
)
from src.backend.core.di.providers.workflow import (
    get_workflow_status_enum_provider as get_workflow_status_enum_provider,
)
from src.backend.core.di.providers.workflow import (
    get_ws_sink_class_provider as get_ws_sink_class_provider,
)
from src.backend.core.di.providers.workflow import (
    set_action_bus_service_provider as set_action_bus_service_provider,
)
from src.backend.core.di.providers.workflow import (
    set_action_dispatcher_provider as set_action_dispatcher_provider,
)
from src.backend.core.di.providers.workflow import (
    set_app_logger_provider as set_app_logger_provider,
)
from src.backend.core.di.providers.workflow import (
    set_correlation_context_setter_provider as set_correlation_context_setter_provider,
)
from src.backend.core.di.providers.workflow import (
    set_di_bridge_dlq_module_provider as set_di_bridge_dlq_module_provider,
)
from src.backend.core.di.providers.workflow import (
    set_dlq_envelope_class_provider as set_dlq_envelope_class_provider,
)
from src.backend.core.di.providers.workflow import (
    set_dlq_memory_writer_module_provider as set_dlq_memory_writer_module_provider,
)
from src.backend.core.di.providers.workflow import (
    set_grpc_logger_provider as set_grpc_logger_provider,
)
from src.backend.core.di.providers.workflow import (
    set_grpc_sink_class_provider as set_grpc_sink_class_provider,
)
from src.backend.core.di.providers.workflow import (
    set_mq_sink_class_provider as set_mq_sink_class_provider,
)
from src.backend.core.di.providers.workflow import (
    set_notifications_module_provider as set_notifications_module_provider,
)
from src.backend.core.di.providers.workflow import (
    set_rate_limiter_provider as set_rate_limiter_provider,
)
from src.backend.core.di.providers.workflow import (
    set_reply_channel_class_provider as set_reply_channel_class_provider,
)
from src.backend.core.di.providers.workflow import (
    set_resilience_components_report_provider as set_resilience_components_report_provider,
)
from src.backend.core.di.providers.workflow import (
    set_resilience_coordinator_provider as set_resilience_coordinator_provider,
)
from src.backend.core.di.providers.workflow import (
    set_scheduler_manager_provider as set_scheduler_manager_provider,
)
from src.backend.core.di.providers.workflow import (
    set_sink_factory_provider as set_sink_factory_provider,
)
from src.backend.core.di.providers.workflow import (
    set_soap_sink_class_provider as set_soap_sink_class_provider,
)
from src.backend.core.di.providers.workflow import (
    set_stream_dlq_writer_provider as set_stream_dlq_writer_provider,
)
from src.backend.core.di.providers.workflow import (
    set_stream_logger_provider as set_stream_logger_provider,
)
from src.backend.core.di.providers.workflow import (
    set_workflow_backend_factory_provider as set_workflow_backend_factory_provider,
)
from src.backend.core.di.providers.workflow import (
    set_workflow_event_store_provider as set_workflow_event_store_provider,
)
from src.backend.core.di.providers.workflow import (
    set_workflow_factory_module_provider as set_workflow_factory_module_provider,
)
from src.backend.core.di.providers.workflow import (
    set_workflow_main_session_provider as set_workflow_main_session_provider,
)
from src.backend.core.di.providers.workflow import (
    set_workflow_state_repository_provider as set_workflow_state_repository_provider,
)
from src.backend.core.di.providers.workflow import (
    set_workflow_state_store_provider as set_workflow_state_store_provider,
)
from src.backend.core.di.providers.workflow import (
    set_ws_sink_class_provider as set_ws_sink_class_provider,
)
