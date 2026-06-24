"""Фасадные функции и реэкспорт `Pipeline` для frontend (R3.10d → 0 violations).

Цель — изолировать Streamlit-pages от прямых импортов в
``src.backend.dsl.*`` / ``src.backend.entrypoints.*``. Все вызовы
делаются через тонкие async/sync-обёртки этого модуля.

Импорты DSL/entrypoints выполняются здесь (services-слой имеет на это
право: ``services → dsl`` через registries — допустимый паттерн,
а ``services → entrypoints`` для агрегатора audit-стрима — узкое
ис­ключение, оформленное allowlist'ом ``check_layers``).

S44 W2: добавлены символы для миграции 12 frontend→dsl imports (deep-audit S2):
- get_global_registry, WorkflowDeclaration, to_mermaid, compute_step_diff,
  to_graphviz, dry_run_route, waterfall_lines.
S168 W14: добавлены импорты WorkflowDeclaration, compute_step_diff,
  to_graphviz, to_mermaid, dry_run_route, waterfall_lines,
  get_global_registry, load_workflow_from_yaml, load_pipeline_from_yaml.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.backend.dsl.engine.execution_engine import ExecutionEngine
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.tracer import get_tracer
from src.backend.dsl.registry import route_registry
from src.backend.services.workflows.template_registry import get_template_registry


def list_workflow_templates() -> list[Any]:
    """S6 fix: тонкая facade-обёртка над :func:`services.workflows.template_registry.get_template_registry`.

    Возвращает список зарегистрированных workflow-шаблонов. Заменяет
    прямой импорт ``src.backend.services.workflows.template_registry``
    из frontend (R3.10d / S44).

    Returns:
        Список :class:`WorkflowTemplate` (отсортирован по ``registry.load_all()``).
    """
    registry = get_template_registry()
    return list(registry.load_all())


def search_workflow_templates(query: str, top_k: int = 10) -> list[Any]:
    """S6 fix: семантический поиск по workflow templates."""
    registry = get_template_registry()
    return registry.search_semantic(query, top_k=top_k)


def get_ai_cost_snapshot(
    *,
    window_hours: int = 24,
    tenant_id: str | None = None,
    model_filter: str | None = None,
    pipeline_filter: str | None = None,
    top_n: int = 50,
) -> dict[str, Any]:
    """S6 fix: snapshot AI cost через :class:`AICostDashboard`."""
    import asyncio as _asyncio

    from src.backend.services.ai.costs import AICostDashboard

    dashboard = AICostDashboard()
    return _asyncio.run(
        dashboard.snapshot(
            window_hours=window_hours,
            tenant_id=tenant_id,
            model_filter=model_filter,
            pipeline_filter=pipeline_filter,
            top_n=top_n,
        )
    )


def get_default_stuck_monitor() -> Any:
    """S6 fix: facade для ``services.messaging.outbox_monitor``."""
    from src.backend.services.messaging.outbox_monitor import default_stuck_monitor

    return default_stuck_monitor


def get_whoosh_index() -> Any:
    """S6 fix: facade для ``services.wiki.whoosh_index``."""
    from src.backend.services.wiki.whoosh_index import WhooshIndex

    return WhooshIndex


def get_saga_history(workflow_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """S6 fix: facade для saga history service."""
    import asyncio as _asyncio

    from src.backend.services.workflows.saga_history import get_saga_history

    return _asyncio.run(get_saga_history(workflow_id, limit=limit))


def get_saga_stats(
    tenant_id: str | None = None, *, from_dt: Any = None, to_dt: Any = None
) -> dict[str, Any]:
    """S6 fix: aggregate saga statistics."""
    import asyncio as _asyncio

    from src.backend.services.workflows.saga_history import aggregate_saga_stats

    return _asyncio.run(
        aggregate_saga_stats(tenant_id=tenant_id, from_dt=from_dt, to_dt=to_dt)
    )


def get_import_service() -> Any:
    """S6 fix: facade для ``services.integrations.get_import_service``."""
    from src.backend.services.integrations import get_import_service

    return get_import_service()


def get_dsl_builder_service() -> Any:
    """S6 fix: facade для ``services.dsl.builder_service``."""
    from src.backend.services.dsl.builder_service import (
        get_dsl_builder_service as _get_dsl_builder_service,
    )

    return _get_dsl_builder_service()


def list_route_ids() -> list[str]:
    """Возвращает список идентификаторов зарегистрированных DSL-маршрутов."""
    return list(route_registry._routes.keys())


def get_route_pipeline(route_id: str) -> Pipeline | None:
    """Возвращает Pipeline по ``route_id`` или ``None``."""
    try:
        return route_registry.get(route_id)
    except Exception as _:
        return None


def execute_route(route_id: str, body: Any) -> dict[str, Any]:
    """Sync-фасад над ExecutionEngine.execute (для Streamlit)."""
    pipeline = get_route_pipeline(route_id)
    if pipeline is None:
        return {
            "status": "failed",
            "body": None,
            "error": f"route {route_id!r} не найден",
            "trace": [],
        }
    engine = ExecutionEngine()
    exchange = asyncio.run(engine.execute(pipeline, body=body))
    return {
        "status": exchange.status.value,
        "body": (
            exchange.out_message.body
            if exchange.out_message is not None
            else exchange.in_message.body
        ),
        "error": exchange.error,
        "trace": list(exchange.properties.get("_trace", [])),
    }


def list_audit_records(*, count: int = 50) -> list[dict[str, Any]]:
    """Sync-фасад над audit_replay middleware list_audit_records."""
    from src.backend.entrypoints.middlewares.audit_replay import (
        list_audit_records as _list,
    )

    return asyncio.run(_list(count=count))


def list_recent_trace_events(*, limit: int = 100) -> list[dict[str, Any]]:
    """Возвращает последние N trace-событий из ExecutionTracer."""
    tracer = get_tracer()
    events = list(getattr(tracer, "_recent_events", []) or [])
    return events[-limit:]
