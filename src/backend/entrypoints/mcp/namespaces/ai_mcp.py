"""AI namespace MCP tools (ADR-0070 §1, S32 W3).

AI namespace содержит все actions с prefix ``ai.``, ``ml.``, ``rag.``, ``embed.``.
Owner: AI Platform Team.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


# Prefixes для AI namespace
AI_ACTION_PREFIXES = ("ai.", "ml.", "rag.", "embed.")


def register_ai_tools(mcp: FastMCP) -> None:
    """Регистрирует все AI/ML/RAG actions как MCP tools в namespace.

    Args:
        mcp: Экземпляр FastMCP.
    """
    from src.backend.dsl.commands.registry import action_handler_registry

    ai_actions = [
        name
        for name in action_handler_registry.list_actions()
        if any(name.startswith(prefix) for prefix in AI_ACTION_PREFIXES)
    ]

    for action_name in ai_actions:
        _register_ai_tool(mcp, action_name)


def _register_ai_tool(mcp: FastMCP, action_name: str) -> None:
    """Регистрирует один AI/ML action как MCP tool."""
    import inspect

    from src.backend.entrypoints.mcp.mcp_server import _action_input_schema_json
    from src.backend.schemas.invocation import ActionCommandSchema

    schema = _action_input_schema_json(action_name)

    tool_name = action_name.replace(".", "_")
    description = f"AI namespace: {action_name}"

    tool_kwargs: dict[str, object] = {"name": tool_name, "description": description}
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
        import orjson

        from src.backend.dsl.commands.registry import action_handler_registry
        from src.backend.entrypoints.mcp.mcp_server import _check_mcp_tool_authz

        # AI namespace authz gate
        deny_reason = _check_mcp_tool_authz(_action)
        if deny_reason is not None:
            return orjson.dumps(
                {"error": "mcp.tool.denied", "action": _action, "reason": deny_reason}
            ).decode()

        try:
            parsed_payload = orjson.loads(payload) if payload else {}
        except orjson.JSONDecodeError, TypeError:
            parsed_payload = {"raw": payload}

        command = ActionCommandSchema(
            action=_action,
            payload=parsed_payload,
            meta={"source": "mcp", "namespace": "ai"},
        )

        try:
            result = await action_handler_registry.dispatch(command)
            if result is None:
                return orjson.dumps(
                    {"error": "action_returned_null", "action": _action}
                ).decode()
            if hasattr(result, "model_dump"):
                return orjson.dumps(result.model_dump(mode="json")).decode()
            return orjson.dumps(result).decode()
        except Exception as exc:
            return orjson.dumps({"error": str(exc)}).decode()
