"""MCP-сервер на базе FastMCP.

Автоматически экспортирует все зарегистрированные actions
из ActionHandlerRegistry как MCP tools. Дополнительно предоставляет
инструментальные tools для управления маршрутами, конвертации
форматов, шаблонов и мониторинга.

Категории tools:
- Action tools: автогенерация из ActionHandlerRegistry (50+)
- Route tools: list/execute/inspect DSL маршруты
- Template tools: list/instantiate шаблоны Pipeline
- Convert tools: конвертация форматов (JSON↔XML/YAML/CSV/MsgPack)
- System tools: health check, metrics, feature flags
"""

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.core.serialization.msgspec_hotpath import encode_json

logger = get_logger(__name__)




# ── YAML tools (_register_yaml_tools) ──

def _register_yaml_tools(mcp: Any) -> None:
    """Tools для работы с YAML-определениями pipelines."""

    @mcp.tool(
        name="pipeline_export",
        description="Экспортирует DSL-маршрут в YAML формат. "
        "Полезно для backup, версионирования, передачи конфигураций.",
    )
    async def pipeline_export(route_id: str) -> str:
        from src.backend.dsl.registry import route_registry

        try:
            import yaml
        except ImportError:
            return encode_json({"error": "PyYAML not installed"}).decode("utf-8")

        pipeline = route_registry.get_optional(route_id)
        if not pipeline:
            return encode_json({"error": f"Route '{route_id}' not found"}).decode(
                "utf-8"
            )

        spec = {
            "route_id": pipeline.route_id,
            "source": pipeline.source,
            "description": pipeline.description,
            "processors": [
                {type(p).__name__: {"name": p.name}} for p in pipeline.processors
            ],
        }
        return yaml.dump(
            spec, default_flow_style=False, allow_unicode=True, sort_keys=False
        )

    @mcp.tool(
        name="pipeline_from_yaml",
        description="Создаёт DSL-маршрут из YAML и регистрирует в route_registry. "
        "YAML должен содержать: route_id, source, processors (list).",
    )
    async def pipeline_from_yaml(yaml_str: str) -> str:
        from src.backend.dsl.registry import route_registry

        try:
            from src.backend.dsl.yaml_loader import load_pipeline_from_yaml
        except ImportError:
            return encode_json({"error": "yaml_loader not available"}).decode("utf-8")

        try:
            pipeline = load_pipeline_from_yaml(yaml_str)
            route_registry.register(pipeline)
            return encode_json(
                {
                    "status": "registered",
                    "route_id": pipeline.route_id,
                    "processors": len(pipeline.processors),
                }
            ).decode("utf-8")
        except Exception as exc:
            return encode_json({"error": str(exc)}).decode("utf-8")

    @mcp.tool(
        name="route_metrics",
        description="Возвращает SLO-метрики выполнения DSL-маршрутов: "
        "количество вызовов, ошибки, latency P50/P95/P99.",
    )
    async def route_metrics(route_id: str | None = None) -> str:
        try:
            from src.backend.core.di.providers import get_slo_tracker_provider

            tracker = get_slo_tracker_provider()
            report = tracker.get_report()
            if route_id:
                return encode_json({route_id: report.get(route_id, {})}).decode("utf-8")
            return encode_json(report).decode("utf-8")
        except Exception as exc:
            return encode_json({"error": str(exc)}).decode("utf-8")

