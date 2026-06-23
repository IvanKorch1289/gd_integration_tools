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

logger = get_logger(__name__)


# ── shared helpers (action input schema, authz check, single tool registration) ──


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
        from src.backend.core.config.ai_stack import mcp_settings

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
        from src.backend.core.config.ai_stack import mcp_settings
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
