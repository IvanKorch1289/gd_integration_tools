"""DSL Hot Reload — перезагрузка маршрутов из YAML без рестарта.

Отслеживает .dsl.yaml файлы в указанной директории.
При изменении — парсит YAML → строит Pipeline → перерегистрирует.

Формат YAML:
    route_id: orders.create
    source: internal:orders.create
    description: Create order with validation
    feature_flag: beta_orders   # optional
    processors:
      - type: validate
        schema: OrderSchemaIn
      - type: dispatch_action
        action: orders.add
      - type: log
        level: info
"""

import logging
from pathlib import Path
from typing import Any

__all__ = ("DSLHotReloader", "load_yaml_route")

logger = logging.getLogger("dsl.hot_reload")

_PROCESSOR_MAP: dict[str, str] = {
    # Basic
    "set_header": "SetHeaderProcessor",
    "set_property": "SetPropertyProcessor",
    "dispatch_action": "DispatchActionProcessor",
    "transform": "TransformProcessor",
    "filter": "FilterProcessor",
    "enrich": "EnrichProcessor",
    "log": "LogProcessor",
    "validate": "ValidateProcessor",
    # External
    "mcp_tool": "MCPToolProcessor",
    "agent_graph": "AgentGraphProcessor",
    "cdc": "CDCProcessor",
    # Control flow
    "choice": "ChoiceProcessor",
    "try_catch": "TryCatchProcessor",
    "retry": "RetryProcessor",
    "pipeline_ref": "PipelineRefProcessor",
    "parallel": "ParallelProcessor",
    # EIP
    "saga": "SagaProcessor",
    "dead_letter": "DeadLetterProcessor",
    "idempotent": "IdempotentConsumerProcessor",
    "fallback": "FallbackChainProcessor",
    "wire_tap": "WireTapProcessor",
    "translate": "MessageTranslatorProcessor",
    "dynamic_route": "DynamicRouterProcessor",
    "scatter_gather": "ScatterGatherProcessor",
    "throttle": "ThrottlerProcessor",
    "delay": "DelayProcessor",
    "split": "SplitterProcessor",
    "aggregate": "AggregatorProcessor",
    "recipient_list": "RecipientListProcessor",
    # AI
    "prompt_compose": "PromptComposerProcessor",
    "llm_call": "LLMCallProcessor",
    "llm_parse": "LLMParserProcessor",
    "token_budget": "TokenBudgetProcessor",
    "vector_search": "VectorSearchProcessor",
    "sanitize_pii": "SanitizePIIProcessor",
    "restore_pii": "RestorePIIProcessor",
    "event_publish": "EventPublishProcessor",
    "memory_load": "MemoryLoadProcessor",
    "memory_save": "MemorySaveProcessor",
}


def _build_processor(spec: dict[str, Any]) -> Any:
    """Создаёт процессор из YAML-спецификации.

    Порядок поиска:
    1. Plugin Registry (динамически зарегистрированные)
    2. Built-in map (_PROCESSOR_MAP)
    3. Прямое имя класса из processors module
    """
    from src.dsl.engine import processors as proc_mod
    from src.dsl.engine.plugin_registry import get_processor_plugin_registry

    proc_type = spec.get("type", "")
    kwargs: dict[str, Any] = {k: v for k, v in spec.items() if k != "type"}

    plugin_registry = get_processor_plugin_registry()
    if plugin_registry.is_registered(proc_type):
        return plugin_registry.create(proc_type, **kwargs)

    class_name = _PROCESSOR_MAP.get(proc_type, proc_type)
    cls = getattr(proc_mod, class_name, None)
    if cls is None:
        raise ValueError(f"Unknown processor type: {proc_type} ({class_name})")

    return cls(**kwargs)


def load_yaml_route(yaml_path: Path) -> Any:
    """Загружает DSL-маршрут из YAML-файла.

    Args:
        yaml_path: Путь к .dsl.yaml файлу.

    Returns:
        Pipeline: Готовый маршрут.
    """
    import yaml

    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "route_id" not in data:
        raise ValueError(f"Invalid DSL YAML: missing 'route_id' in {yaml_path}")

    from src.dsl.engine.pipeline import Pipeline

    processors = []
    for proc_spec in data.get("processors", []):
        processors.append(_build_processor(proc_spec))

    return Pipeline(
        route_id=data["route_id"],
        source=data.get("source"),
        description=data.get("description"),
        processors=processors,
        feature_flag=data.get("feature_flag"),
    )


class DSLHotReloader:
    """Отслеживает .dsl.yaml файлы и перезагружает маршруты."""

    def __init__(self, dsl_dir: Path) -> None:
        self._dir = dsl_dir

    def load_all(self) -> int:
        """Загружает все .dsl.yaml из директории при старте."""
        from src.dsl.commands.registry import route_registry

        if not self._dir.exists():
            return 0

        count = 0
        for yaml_file in sorted(self._dir.glob("**/*.dsl.yaml")):
            try:
                pipeline = load_yaml_route(yaml_file)
                route_registry.register(pipeline)
                logger.info(
                    "Loaded YAML route: %s from %s", pipeline.route_id, yaml_file.name
                )
                count += 1
            except Exception as exc:
                logger.error("Failed to load %s: %s", yaml_file, exc)

        return count

    async def watch(self) -> None:
        """Фоновая задача: watch файлы и перезагружать при изменении."""
        try:
            from watchfiles import awatch
        except ImportError:
            logger.warning("watchfiles не установлен — hot reload отключён")
            return

        from src.dsl.commands.registry import route_registry

        logger.info("DSL Hot Reload watching: %s", self._dir)

        async for changes in awatch(self._dir):
            for change_type, file_path in changes:
                path = Path(file_path)
                if not path.name.endswith(".dsl.yaml"):
                    continue

                try:
                    pipeline = load_yaml_route(path)
                    route_registry.register(pipeline)
                    logger.info("Hot-reloaded route: %s", pipeline.route_id)
                except Exception as exc:
                    logger.error("Hot reload failed for %s: %s", path, exc)
