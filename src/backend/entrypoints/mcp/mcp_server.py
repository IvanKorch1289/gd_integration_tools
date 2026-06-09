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

import orjson

from src.backend.core.logging import get_logger
from src.backend.core.serialization.msgspec_hotpath import encode_json

__all__ = ("create_mcp_server", "register_mcp_tools")

logger = get_logger(__name__)


def create_mcp_server() -> Any:
    """Создаёт и настраивает FastMCP-сервер.

    Returns:
        Экземпляр FastMCP.

    Raises:
        ImportError: Если fastmcp не установлен.
    """
    from fastmcp import FastMCP

    mcp = FastMCP(
        "GD Integration Tools",
        description="MCP-сервер интеграционной шины GD. "
        "Предоставляет бизнес-actions, управление маршрутами, "
        "конвертацию форматов, шаблоны и мониторинг.",
    )

    register_mcp_tools(mcp)
    _register_route_tools(mcp)
    _register_template_tools(mcp)
    _register_convert_tools(mcp)
    _register_system_tools(mcp)
    _register_yaml_tools(mcp)
    _register_document_tools(mcp)

    # S32 W3: AI namespace tools
    try:
        from src.backend.entrypoints.mcp.namespaces.ai_mcp import register_ai_tools

        register_ai_tools(mcp)
    except Exception as exc:
        logger.debug("AI namespace MCP tools registration skipped: %s", exc)

    # IL-WF1.5: auto-export durable workflows как MCP tools
    # (CrewAI / LangChain / LangGraph получают каждый workflow
    # отдельным tool'ом с валидацией payload через input_schema).
    try:
        from src.backend.entrypoints.mcp.workflow_tools import register_workflow_tools

        register_workflow_tools(mcp)
    except Exception as exc:
        logger.warning("workflow MCP tools registration skipped: %s", exc)

    return mcp


def register_mcp_tools(mcp: Any) -> None:
    """Регистрирует все actions из ActionHandlerRegistry как MCP tools.

    Args:
        mcp: Экземпляр FastMCP.
    """
    from src.backend.dsl.commands.registry import action_handler_registry

    for action_name in action_handler_registry.list_actions():
        _register_single_tool(mcp, action_name)

    logger.info(
        "Зарегистрировано %d action MCP tools",
        len(action_handler_registry.list_actions()),
    )


def _action_input_schema_json(action_name: str) -> dict[str, Any] | None:
    """Извлекает JSON-Schema payload-модели action'а.

    Источник — :class:`ActionMetadata.input_model` (Pydantic). Возвращает
    ``None`` если модель не зарегистрирована или интроспекция не удалась.
    Используется для обогащения MCP tool description (Stream E.2) —
    клиент видит ожидаемую структуру payload.
    """
    from src.backend.dsl.commands.registry import action_handler_registry

    metadata = action_handler_registry.get_metadata(action_name)
    if metadata is None or metadata.input_model is None:
        return None
    try:
        return metadata.input_model.model_json_schema()
    except Exception as _:
        return None


def _register_single_tool(mcp: Any, action_name: str) -> None:
    """Регистрирует один action как MCP tool с input_schema из ActionSpec.

    Wave D.4 / Track D AI: schema переехала из description в native
    параметр ``inputSchema`` FastMCP. При ``MCP_LEGACY_DESCRIPTION_SCHEMA=true``
    схема ДОПОЛНИТЕЛЬНО встраивается в description (graceful migration
    существующих клиентов). Поддержка native параметра feature-detected
    через ``inspect.signature``.
    """
    import inspect

    from src.backend.dsl.commands.registry import action_handler_registry
    from src.backend.schemas.invocation import ActionCommandSchema

    schema = _action_input_schema_json(action_name)
    description_parts = [f"Выполняет action '{action_name}' через интеграционную шину."]

    legacy_inline = False
    try:
        from src.backend.core.config.ai_2026 import mcp_settings

        legacy_inline = bool(mcp_settings.legacy_description_schema)
    except Exception as _:
        legacy_inline = False

    if schema is not None and legacy_inline:
        description_parts.append(
            "Payload (JSON-Schema): " + encode_json(schema).decode("utf-8")
        )

    tool_kwargs: dict[str, Any] = {
        "name": action_name.replace(".", "_"),
        "description": " ".join(description_parts),
    }
    if schema is not None:
        try:
            tool_sig = inspect.signature(mcp.tool)
            if "input_schema" in tool_sig.parameters:
                tool_kwargs["input_schema"] = schema
            elif "inputSchema" in tool_sig.parameters:
                tool_kwargs["inputSchema"] = schema
        except TypeError, ValueError:
            pass

    @mcp.tool(**tool_kwargs)
    async def tool_handler(payload: str = "{}", _action: str = action_name) -> str:
        # Block 1.4 (gap-ai-1.4, ADR-0072): per-tool authz fail-closed.
        # При tool_authz_enabled=True action_name проходит проверку
        # _check_mcp_tool_authz() — public namespace OR explicit allowlist.
        # При denied возвращаем error-envelope + audit-event без dispatch.
        deny_reason = _check_mcp_tool_authz(_action)
        if deny_reason is not None:
            logger.warning(
                "mcp_tool_denied",
                extra={"action": _action, "reason": deny_reason, "source": "mcp"},
            )
            return encode_json(
                {"error": "mcp.tool.denied", "action": _action, "reason": deny_reason}
            ).decode("utf-8")

        try:
            parsed_payload = orjson.loads(payload) if payload else {}
        except orjson.JSONDecodeError, TypeError:
            parsed_payload = {"raw": payload}

        command = ActionCommandSchema(
            action=_action, payload=parsed_payload, meta={"source": "mcp"}
        )

        try:
            result = await action_handler_registry.dispatch(command)
            if hasattr(result, "model_dump"):
                return encode_json(result.model_dump(mode="json")).decode("utf-8")
            return encode_json(result).decode("utf-8")
        except Exception as exc:
            return encode_json({"error": str(exc)}).decode("utf-8")


def _check_mcp_tool_authz(action_name: str) -> str | None:
    """Block 1.4: per-tool authz для MCP dispatch (fail-closed).

    Возвращает причину деная (str) либо ``None`` если доступ разрешён.

    Алгоритм:
        1. При ``mcp_settings.tool_authz_enabled=False`` → allow (passthrough).
        2. Иначе:
           a. action_name в ``tool_allowlist`` → allow;
           b. namespace action в ``tool_public_namespaces`` → allow;
           c. namespace имеет ``capabilities_required`` → CapabilityGate.check;
           d. иначе → deny с причиной ``"not_in_allowlist_or_public_ns"``.

    Tenant-aware фильтрация (per-tenant action whitelist) — carryover
    в Block 9.1 (SkillRegistry per-tenant tools filter, Phase E).

    Args:
        action_name: Имя action из ActionHandlerRegistry.

    Returns:
        Причина деная (str) либо None.
    """
    try:
        from src.backend.core.config.ai_2026 import mcp_settings
    except Exception as _:
        return None
    if not mcp_settings.tool_authz_enabled:
        return None

    if action_name in set(mcp_settings.tool_allowlist):
        return None

    namespace = action_name.split(".", 1)[0] if "." in action_name else action_name
    public_namespaces = set(mcp_settings.tool_public_namespaces)
    if namespace in public_namespaces:
        return None

    # Capability check via MCPNamespace.capabilities_required (ADR-0070 §3)
    try:
        from src.backend.core.security.capabilities import CapabilityDeniedError
        from src.backend.core.security.capabilities.gate import CapabilityGate
        from src.backend.entrypoints.mcp.namespaces import get_namespace_for_action

        ns = get_namespace_for_action(action_name)
        if ns is not None and ns.capabilities_required:
            gate = CapabilityGate()
            for cap in ns.capabilities_required:
                try:
                    gate.check(plugin="mcp", capability=cap, requested_scope=None)
                except CapabilityDeniedError:
                    return f"capability_denied:{cap}"
    except Exception as _:
        # Best-effort: capability check failure → deny
        return "capability_check_failed"

    return "not_in_allowlist_or_public_ns"


# ── Route Management Tools ──


def _register_route_tools(mcp: Any) -> None:
    """Tools для управления DSL-маршрутами."""

    @mcp.tool(
        name="route_list",
        description="Список всех зарегистрированных DSL-маршрутов с описаниями и процессорами",
    )
    async def route_list() -> str:
        from src.backend.dsl.registry import route_registry

        routes = []
        for rid in route_registry.list_routes():
            pipeline = route_registry.get_optional(rid)
            if pipeline:
                routes.append(
                    {
                        "route_id": rid,
                        "source": pipeline.source,
                        "description": pipeline.description,
                        "processor_count": len(pipeline.processors),
                        "processors": [p.name for p in pipeline.processors],
                        "protocol": pipeline.protocol.value
                        if pipeline.protocol
                        else None,
                    }
                )
        return encode_json(routes).decode("utf-8")

    @mcp.tool(
        name="route_execute",
        description="Выполняет DSL-маршрут по route_id с указанным payload. Возвращает результат Exchange.",
    )
    async def route_execute(route_id: str, payload: str = "{}") -> str:
        from src.backend.dsl.engine.execution_engine import ExecutionEngine
        from src.backend.dsl.registry import route_registry

        try:
            pipeline = route_registry.get(route_id)
        except KeyError:
            return encode_json({"error": f"Route '{route_id}' not found"}).decode(
                "utf-8"
            )

        try:
            parsed = orjson.loads(payload) if payload else {}
        except orjson.JSONDecodeError, TypeError:
            parsed = {"raw": payload}

        engine = ExecutionEngine()
        exchange = await engine.execute(pipeline, body=parsed)

        result = (
            exchange.out_message.body
            if exchange.out_message
            else exchange.in_message.body
        )
        return encode_json(
            {
                "status": exchange.status.value,
                "result": result,
                "error": exchange.error,
                "properties": {
                    k: v
                    for k, v in exchange.properties.items()
                    if not k.startswith("_")
                },
            }
        ).decode("utf-8")

    @mcp.tool(
        name="route_inspect",
        description="Детальная информация о DSL-маршруте: процессоры, pipeline metadata, feature flags.",
    )
    async def route_inspect(route_id: str) -> str:
        from src.backend.dsl.registry import route_registry

        pipeline = route_registry.get_optional(route_id)
        if not pipeline:
            return encode_json({"error": f"Route '{route_id}' not found"}).decode(
                "utf-8"
            )

        return encode_json(
            {
                "route_id": pipeline.route_id,
                "source": pipeline.source,
                "description": pipeline.description,
                "protocol": pipeline.protocol.value if pipeline.protocol else None,
                "feature_flag": pipeline.feature_flag,
                "processors": [
                    {"name": p.name, "type": type(p).__name__}
                    for p in pipeline.processors
                ],
            }
        ).decode("utf-8")


# ── Template Tools ──


def _register_template_tools(mcp: Any) -> None:
    """Tools для работы с шаблонами Pipeline."""

    @mcp.tool(
        name="template_list",
        description="Список всех доступных шаблонов DSL Pipeline с параметрами. "
        "Шаблоны — готовые паттерны для типовых задач (ETL, scraping, AI Q&A, CRUD и т.д.).",
    )
    async def template_list() -> str:
        from src.backend.dsl.templates_library import list_templates

        return encode_json(list_templates()).decode("utf-8")

    @mcp.tool(
        name="template_instantiate",
        description="Создаёт Pipeline из шаблона с указанными параметрами. "
        'Пример: template_id=\'etl.postgres_to_clickhouse\', params=\'{"source_query": "SELECT...", "target_table": "analytics.orders"}\'',
    )
    async def template_instantiate(template_id: str, params: str = "{}") -> str:
        from src.backend.dsl.templates_library import templates

        tmpl = templates.get(template_id)
        if not tmpl:
            return encode_json({"error": f"Template '{template_id}' not found"}).decode(
                "utf-8"
            )

        try:
            parsed_params = orjson.loads(params) if params else {}
        except orjson.JSONDecodeError, TypeError:
            return encode_json({"error": "Invalid JSON params"}).decode("utf-8")

        try:
            result = tmpl.builder(**parsed_params)
            if isinstance(result, list):
                return encode_json(
                    {
                        "status": "ok",
                        "pipelines": [
                            {"route_id": p.route_id, "processors": len(p.processors)}
                            for p in result
                        ],
                    }
                ).decode("utf-8")
            return encode_json(
                {
                    "status": "ok",
                    "route_id": result.route_id,
                    "processors": len(result.processors),
                    "processor_names": [p.name for p in result.processors],
                }
            ).decode("utf-8")
        except Exception as exc:
            return encode_json({"error": str(exc)}).decode("utf-8")

    @mcp.tool(
        name="macro_list",
        description="Список всех DSL-макросов (pre-built pipeline patterns). "
        "Макросы — функции для создания типовых интеграционных pipelines.",
    )
    async def macro_list() -> str:
        import inspect

        from src.backend.dsl import macros

        result = []
        for name in macros.__all__:
            fn = getattr(macros, name, None)
            if fn and callable(fn):
                sig = inspect.signature(fn)
                result.append(
                    {
                        "name": name,
                        "doc": (fn.__doc__ or "").split("\n")[0],
                        "parameters": [
                            {
                                "name": p.name,
                                "default": str(p.default)
                                if p.default != inspect.Parameter.empty
                                else None,
                            }
                            for p in sig.parameters.values()
                        ],
                    }
                )
        return encode_json(result).decode("utf-8")


# ── Format Conversion Tools ──


def _register_convert_tools(mcp: Any) -> None:
    """Tools для конвертации форматов данных."""

    @mcp.tool(
        name="convert_format",
        description="Конвертирует данные между форматами: json, yaml, xml, csv, msgpack, bson. "
        "Пример: from_format='json', to_format='yaml', data='{\"key\": \"value\"}'",
    )
    async def convert_format(from_format: str, to_format: str, data: str) -> str:
        from src.backend.dsl.engine.processors.converters import _STRATEGIES

        key = f"{from_format}→{to_format}"
        strategy = _STRATEGIES.get(key)
        if not strategy:
            available = list(_STRATEGIES.keys())
            return encode_json(
                {"error": f"No converter for {key}", "available": available}
            ).decode("utf-8")

        try:
            input_data: Any = data
            if from_format in ("json", "dict"):
                try:
                    input_data = orjson.loads(data)
                except orjson.JSONDecodeError, TypeError:
                    pass

            result = strategy.convert(input_data)

            if isinstance(result, bytes):
                import base64

                return encode_json(
                    {
                        "format": to_format,
                        "encoding": "base64",
                        "data": base64.b64encode(result).decode("utf-8"),
                    }
                ).decode("utf-8")

            if isinstance(result, str):
                return result

            return encode_json(result).decode("utf-8")
        except Exception as exc:
            return encode_json({"error": str(exc)}).decode("utf-8")

    @mcp.tool(
        name="convert_list_formats",
        description="Показывает все доступные конвертации форматов (from→to пары).",
    )
    async def convert_list_formats() -> str:
        from src.backend.dsl.engine.processors.converters import _STRATEGIES

        return encode_json(list(_STRATEGIES.keys())).decode("utf-8")


# ── System/Monitoring Tools ──


def _register_system_tools(mcp: Any) -> None:
    """Tools для мониторинга и управления системой."""

    @mcp.tool(
        name="system_health",
        description="Проверка здоровья всех компонентов системы (DB, Redis, S3, ES, etc.).",
    )
    async def system_health() -> str:
        from src.backend.dsl.commands.registry import action_handler_registry
        from src.backend.schemas.invocation import ActionCommandSchema

        try:
            result = await action_handler_registry.dispatch(
                ActionCommandSchema(action="tech.check_all_services", payload={})
            )
            if hasattr(result, "model_dump"):
                return encode_json(result.model_dump(mode="json")).decode("utf-8")
            return encode_json(result).decode("utf-8")
        except Exception as exc:
            return encode_json({"error": str(exc)}).decode("utf-8")

    @mcp.tool(
        name="system_actions",
        description="Список всех доступных actions с группировкой по домену. "
        "Полезно для обнаружения возможностей системы.",
    )
    async def system_actions() -> str:
        from src.backend.dsl.commands.registry import action_handler_registry

        actions = action_handler_registry.list_actions()
        domains: dict[str, list[str]] = {}
        for action in actions:
            domain = action.split(".")[0] if "." in action else "other"
            domains.setdefault(domain, []).append(action)

        return encode_json({"total": len(actions), "domains": domains}).decode("utf-8")

    @mcp.tool(
        name="system_processors",
        description="Список всех доступных DSL-процессоров с описаниями. "
        "Процессоры — строительные блоки для создания интеграционных маршрутов.",
    )
    async def system_processors() -> str:
        import inspect

        from src.backend.dsl.engine import processors as proc_module

        result = []
        for name in dir(proc_module):
            obj = getattr(proc_module, name, None)
            if (
                inspect.isclass(obj)
                and name.endswith("Processor")
                and name != "BaseProcessor"
                and name != "CallableProcessor"
            ):
                doc = (obj.__doc__ or "").strip().split("\n")[0]
                result.append({"name": name, "description": doc})

        result.sort(key=lambda x: x["name"])
        return encode_json(result).decode("utf-8")

    @mcp.tool(
        name="system_feature_flags",
        description="Показывает состояние feature flags. "
        "Feature flags позволяют включать/отключать маршруты без рестарта.",
    )
    async def system_feature_flags() -> str:
        from src.backend.core.state.runtime import disabled_feature_flags

        return encode_json({"disabled_flags": list(disabled_feature_flags)}).decode(
            "utf-8"
        )


# ── YAML Pipeline Tools ──


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


# ── Document Tools (Sprint S5 — markitdown integration) ──


def _register_document_tools(mcp: Any) -> None:
    """Tools для работы с файловыми документами (Sprint S5 hotfix).

    ``documents_to_markdown`` — конвертирует файл (PDF/DOCX/PPTX/XLSX/
    HTML/CSV/JSON) в Markdown через markitdown-engine (с legacy
    fallback). Используется AI-агентами для подачи структурированного
    контекста в LLM.
    """

    @mcp.tool(
        name="documents_to_markdown",
        description=(
            "Конвертирует файл в Markdown через markitdown (PDF/DOCX/PPTX/"
            "XLSX/HTML/CSV/JSON/MD/TXT). Возвращает JSON: "
            "{markdown, engine, mime, size_bytes, warnings, filename}. "
            "При недоступности markitdown — fallback на legacy plain-text."
        ),
    )
    async def documents_to_markdown(path: str, mime: str | None = None) -> str:
        from pathlib import Path as _Path

        from src.backend.core.ai.fs_facade import AIFsFacade
        from src.backend.core.ai.workspace_manager import AIWorkspaceManager
        from src.backend.core.config.ai import ai_workspace_settings

        try:
            target = _Path(path)
            if not target.exists():
                return encode_json({"error": f"File not found: {path}"}).decode("utf-8")

            wm = AIWorkspaceManager(root=ai_workspace_settings.workspace_root)
            facade = AIFsFacade(
                workspace_manager=wm, capability_check=None, plugin="mcp"
            )
            text, meta = await facade.read_as_markdown(target, mime=mime)
            return encode_json(
                {
                    "markdown": text,
                    "engine": meta.get("engine"),
                    "mime": meta.get("mime"),
                    "size_bytes": meta.get("size_bytes"),
                    "warnings": list(meta.get("warnings") or []),
                    "filename": meta.get("filename"),
                }
            ).decode("utf-8")
        except Exception as exc:
            return encode_json({"error": str(exc)}).decode("utf-8")
