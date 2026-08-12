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

from typing import Any, Callable

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
            "Payload (JSON-Schema): " + encode_json(schema).decode("utf-8"),
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
        except (TypeError, ValueError):
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
                {"error": "mcp.tool.denied", "action": _action, "reason": deny_reason},
            ).decode("utf-8")

        try:
            parsed_payload = orjson.loads(payload) if payload else {}
        except (orjson.JSONDecodeError, TypeError):
            parsed_payload = {"raw": payload}

        command = ActionCommandSchema(
            action=_action, payload=parsed_payload, meta={"source": "mcp"},
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
    except Exception as exc:
        # Cycle 20 P0-3: fail-CLOSED. Settings import error means we cannot
        # verify policy — deny by default rather than grant.
        # Cycle 77 L1: use module-level canonical logger.
        logger.warning(
            "MCP authz fail-CLOSED: cannot import mcp_settings (%s)", exc,
        )
        return f"mcp_settings unavailable: {type(exc).__name__}"
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
        from src.backend.entrypoints.mcp.namespaces import get_namespace_for_action

        # S201 fix: use CapabilityFacade instead of direct CapabilityGate()
        from src.backend.services.capabilities.facade import get_capability_facade

        ns = get_namespace_for_action(action_name)
        if ns is not None and ns.capabilities_required:
            cap_facade = get_capability_facade()
            for cap in ns.capabilities_required:
                try:
                    cap_facade.check_or_raise(
                        plugin="mcp", capability=cap, scope=None,
                    )
                except CapabilityDeniedError:
                    return f"capability_denied:{cap}"
    except Exception as _:
        # Best-effort: capability check failure → deny
        return "capability_check_failed"

    return "not_in_allowlist_or_public_ns"


# ── manual tool authz wrapper (Block 1.4-extension) ──────────────────
#
# Action tools (ActionHandlerRegistry-backed) вызывают
# ``_check_mcp_tool_authz`` inline в своих handler'ах. Manual tools
# (``route_*``, ``pipeline_*``, ``documents_*``, ``workflow_*``, ...)
# зарегистрированы через :func:`_authz_manual_tool` — единый wrapper
# выше уровня tool function, который делает тот же fail-closed check
# для каждого вызова. При ``tool_authz_enabled=False`` или пустом
# ``tool_manual_allowlist`` — passthrough (backward-compat).


def _check_mcp_manual_tool_authz(tool_name: str) -> str | None:
    """Block 1.4-extension: per-tool authz для manual MCP tools (fail-closed).

    Возвращает причину деная (str) либо ``None`` если доступ разрешён.

    Алгоритм:
        1. ``mcp_settings.tool_authz_enabled=False`` → allow (passthrough).
        2. ``mcp_settings.tool_manual_allowlist`` пуст → allow (passthrough).
        3. ``tool_name`` в ``tool_manual_allowlist`` → allow.
        4. Иначе → deny с причиной ``"not_in_manual_allowlist"``.

    Args:
        tool_name: Имя manual tool (напр. ``"route_execute"``).

    Returns:
        Причина деная (str) либо None.
    """
    try:
        from src.backend.core.config.ai_stack import mcp_settings
    except Exception as exc:
        # Fail-CLOSED — settings import error means we cannot verify policy.
        logger.warning(
            "MCP manual tool authz fail-CLOSED: cannot import mcp_settings (%s)", exc
        )
        return f"mcp_settings unavailable: {type(exc).__name__}"

    if not mcp_settings.tool_authz_enabled:
        return None
    allowlist = set(mcp_settings.tool_manual_allowlist or ())
    if not allowlist:
        # No policy set → passthrough (backward-compat). Оператор явно
        # включает authz, заполняя tool_manual_allowlist.
        return None
    if tool_name in allowlist:
        return None
    return "not_in_manual_allowlist"


def _manual_tool_deny_envelope(tool_name: str, reason: str) -> str:
    """Единый error-envelope для denied manual tool call.

    Args:
        tool_name: Имя tool.
        reason: Причина деная из :func:`_check_mcp_manual_tool_authz`.

    Returns:
        JSON-строка для отдачи клиенту.
    """
    return encode_json(
        {"error": "mcp.tool.denied", "tool": tool_name, "reason": reason}
    ).decode("utf-8")


def _authz_manual_tool(
    mcp: Any, *, name: str, description: str
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: register manual MCP tool с per-call authz wrapper.

    Single wrapper выше уровня tool function (Block 1.4-extension). Заменяет
    прямой вызов ``@mcp.tool(name=..., description=...)`` для manual tools
    (``route_*``, ``pipeline_*``, ``documents_*``, ``workflow_*``, ...).

    При каждом вызове обёрнутого tool'а выполняется
    :func:`_check_mcp_manual_tool_authz`; при deny возвращается error-envelope,
    иначе — делегирование исходной функции. ``functools.wraps`` сохраняет
    сигнатуру/имя/docstring для FastMCP introspection (tool schema строится
    по сигнатуре).

    Args:
        mcp: Экземпляр FastMCP.
        name: Имя tool в реестре MCP.
        description: Описание tool (для MCP-клиента).

    Returns:
        Decorator factory для оборачиваемой функции.
    """
    import functools

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            deny_reason = _check_mcp_manual_tool_authz(name)
            if deny_reason is not None:
                logger.warning(
                    "mcp_manual_tool_denied",
                    extra={"tool": name, "reason": deny_reason, "source": "mcp"},
                )
                return _manual_tool_deny_envelope(name, deny_reason)
            return await fn(*args, **kwargs)

        return mcp.tool(name=name, description=description)(wrapper)

    return decorator
