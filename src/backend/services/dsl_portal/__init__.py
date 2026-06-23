"""Узкий публичный фасад DSL-портала для frontend (R3.10d → 0 violations).

Wave ``[wave:s6/layer-violations-facade]``. Streamlit developer-portal
ранее напрямую импортировал DSL engine, registry, tracer, yaml_loader,
entrypoints middleware — это нарушение слойного контракта (frontend →
backend-services-only, см. ``tools/check_layers.py`` R3.10d).

Этот модуль агрегирует ровно то, что нужно UI:

* загрузка/инспекция Pipeline (engine + yaml_loader);
* список зарегистрированных маршрутов (route_registry);
* запуск с трассировкой (ExecutionEngine + tracer);
* список audit-records (audit_replay middleware).

Из frontend нужно импортировать **только** этот модуль:

    from src.backend.services.dsl_portal import (
        Pipeline, load_pipeline_from_yaml,
        list_route_ids, get_route_pipeline,
        execute_route, list_audit_records, list_recent_trace_events,
    )

Импорт DSL/entrypoints напрямую из frontend остаётся запрещённым
``check_layers.py``.
"""

from __future__ import annotations

from src.backend.services.dsl_portal.builder_facade import (
    Pipeline,
    WorkflowDeclaration,
    compute_step_diff,
    dry_run_route,
    execute_route,
    get_global_registry,
    get_route_pipeline,
    list_audit_records,
    list_recent_trace_events,
    list_route_ids,
    list_workflow_templates,
    load_all_workflows_from_directory,
    load_pipeline_from_yaml,
    load_workflow_from_file,
    load_workflow_from_yaml,
    search_workflow_templates,
    to_graphviz,
    to_mermaid,
    waterfall_lines,
)

__all__ = (
    "Pipeline",
    "WorkflowDeclaration",
    "compute_step_diff",
    "dry_run_route",
    "execute_route",
    "get_global_registry",
    "get_route_pipeline",
    "list_audit_records",
    "list_recent_trace_events",
    "list_route_ids",
    "list_workflow_templates",
    "load_all_workflows_from_directory",
    "load_pipeline_from_yaml",
    "load_workflow_from_file",
    "load_workflow_from_yaml",
    "search_workflow_templates",
    "to_graphviz",
    "to_mermaid",
    "waterfall_lines",
)
