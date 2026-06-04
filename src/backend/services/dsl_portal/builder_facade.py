"""Фасадные функции и реэкспорт `Pipeline` для frontend (R3.10d → 0 violations).

Цель — изолировать Streamlit-pages от прямых импортов в
``src.backend.dsl.*`` / ``src.backend.entrypoints.*``. Все вызовы
делаются через тонкие async/sync-обёртки этого модуля.

Импорты DSL/entrypoints выполняются здесь (services-слой имеет на это
право: ``services → dsl`` через registries — допустимый паттерн,
а ``services → entrypoints`` для агрегатора audit-стрима — узкое
ис­ключение, оформленное allowlist'ом ``check_layers``).
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.backend.dsl.engine.execution_engine import ExecutionEngine
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.tracer import get_tracer
from src.backend.dsl.registry import route_registry
from src.backend.dsl.yaml_loader import load_pipeline_from_yaml

__all__ = (
    "Pipeline",
    "execute_route",
    "get_route_pipeline",
    "list_audit_records",
    "list_recent_trace_events",
    "list_route_ids",
    "load_pipeline_from_yaml",
)


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
    """Sync-фасад над ExecutionEngine.execute (для Streamlit).

    Возвращает компактный dict-снимок результата:
        ``{"status": str, "body": Any, "error": str|None, "trace": list}``.
    """
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
