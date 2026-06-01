"""Wave 8.6 — smoke-проверка MCP экспорта actions.

Гарантирует, что:

1. ``ActionHandlerRegistry`` инициализирован при загрузке action setup;
2. Tier1 (core actions) и Tier2 (DSL-actions) registry экспортируется
   через ``mcp_server.register_mcp_tools()`` без падения;
3. Общий список MCP-tools ≥ количеству ``action_handler_registry.list_actions()``.

Запуск: ``uv run python tools/check_mcp_export.py``.
"""

from __future__ import annotations

import asyncio
import sys


def _check(condition: bool, message: str) -> None:
    if not condition:
        print(f"FAIL: {message}", file=sys.stderr)
        sys.exit(1)


class _CountingMCP:
    """Минимальный stub FastMCP, считающий регистрации tool'ов.

    Wave D.4: stub воспринимает оба параметра — legacy ``description``
    и native ``input_schema``/``inputSchema``.
    """

    def __init__(self) -> None:
        self.tools: list[str] = []
        self.schemas: dict[str, dict] = {}

    def tool(self, *_args, **kwargs):
        name = kwargs.get("name", "<anon>")
        schema = kwargs.get("input_schema") or kwargs.get("inputSchema")

        def decorator(fn):
            self.tools.append(name)
            if isinstance(schema, dict):
                self.schemas[name] = schema
            return fn

        return decorator


async def main() -> int:
    """Регистрирует actions и проверяет MCP экспорт."""
    # Импорт «late» — даёт DSL-setup'у выполниться лениво.
    from src.backend.dsl.commands.registry import action_handler_registry
    from src.backend.dsl.commands.setup import register_action_handlers

    register_action_handlers()

    actions_total = len(action_handler_registry.list_actions())
    _check(
        actions_total > 0,
        "ActionHandlerRegistry пуст — register_action_handlers() не отработал",
    )

    from src.backend.entrypoints.mcp.mcp_server import register_mcp_tools

    mcp = _CountingMCP()
    register_mcp_tools(mcp)

    _check(
        len(mcp.tools) >= actions_total,
        f"MCP экспортировал {len(mcp.tools)} tools, registry содержит {actions_total}",
    )

    print(
        f"OK mcp_export: actions={actions_total} mcp_tools={len(mcp.tools)} "
        f"native_schemas={len(mcp.schemas)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
