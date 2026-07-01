"""Frontend facade для core/ (D271, M24 P0 architecture).

Ponytail YAGNI: thin wrapper re-export core symbols.

G1_FRONTEND: единая точка импорта для Streamlit — re-export из core/ и
services.dsl_portal, чтобы frontend не зависел напрямую от backend-слоёв.
"""
from __future__ import annotations

from src.backend.core.audit.facade import emit_audit_safe
from src.backend.core.config.express import express_settings
from src.backend.core.config.features import feature_flags
from src.backend.core.di.providers import (
    get_express_bot_client_factory_provider,
    get_express_botx_message_class_provider,
)
from src.backend.core.interfaces.import_gateway import (
    ImportSource,
    ImportSourceKind,
)
from src.backend.core.logging import get_logger
from src.backend.core.messaging import (
    FakeOutbox,
    OutboxBackend,
    OutboxEvent,
)
from src.backend.services.dsl_portal import (
    Pipeline,
    WorkflowDeclaration,
    compute_step_diff,
    get_ai_cost_snapshot,
    get_default_stuck_monitor,
    get_dsl_builder_service,
    get_global_registry,
    get_import_service,
    get_saga_history,
    get_saga_stats,
    get_whoosh_index,
    list_audit_records,
    list_recent_trace_events,
    list_route_ids,
    list_workflow_templates,
    load_pipeline_from_yaml,
    search_workflow_templates,
    to_graphviz,
    to_mermaid,
)

__all__ = (
    "express_settings",
    "feature_flags",
    "get_logger",
    "get_express_bot_client_factory_provider",
    "get_express_botx_message_class_provider",
    "FakeOutbox",
    "OutboxBackend",
    "OutboxEvent",
    # G1_FRONTEND: audit
    "emit_audit_safe",
    # G1_FRONTEND: import_gateway
    "ImportSource",
    "ImportSourceKind",
    # G1_FRONTEND: dsl_portal
    "Pipeline",
    "WorkflowDeclaration",
    "compute_step_diff",
    "get_ai_cost_snapshot",
    "get_default_stuck_monitor",
    "get_dsl_builder_service",
    "get_global_registry",
    "get_import_service",
    "get_saga_history",
    "get_saga_stats",
    "get_whoosh_index",
    "list_audit_records",
    "list_recent_trace_events",
    "list_route_ids",
    "list_workflow_templates",
    "load_pipeline_from_yaml",
    "search_workflow_templates",
    "to_graphviz",
    "to_mermaid",
)
