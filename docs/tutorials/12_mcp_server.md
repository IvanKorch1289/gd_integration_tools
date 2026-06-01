# MCP-сервер — FastMCP integration

MCP-сервер автоматически экспортирует все зарегистрированные actions как MCP tools
через FastMCP. Это позволяет AI-агентам (Claude, CrewAI, LangChain) вызывать
бизнес-логику через единый инструментальный интерфейс.

## Архитектура

```
ActionHandlerRegistry
    │  (50+ actions)
    ▼
create_mcp_server()
    ├── register_mcp_tools()       — action tools
    ├── _register_route_tools()    — route list/execute/inspect
    ├── _register_template_tools() — template list/instantiate
    ├── _register_convert_tools()  — format conversion
    ├── _register_system_tools()   — health/metrics/flags
    ├── _register_yaml_tools()     — pipeline export/from_yaml
    ├── _register_document_tools() — documents_to_markdown
    └── register_workflow_tools()  — durable workflow tools
```

## Создание и запуск сервера

```python
from src.backend.entrypoints.mcp.mcp_server import create_mcp_server

mcp = create_mcp_server()

# Запуск HTTP-сервера
mcp.run(transport="http", port=8765)

# Или STDIO для Claude Code CLI
mcp.run(transport="stdio")
```

## Auto-export action как MCP tool

Каждый action из ActionHandlerRegistry автоматически становится MCP tool:

```python
# source: src/backend/entrypoints/mcp/mcp_server.py:73
for action_name in action_handler_registry.list_actions():
    _register_single_tool(mcp, action_name)
```

Tool name формируется заменой `.` на `_`:
- `orders.add` → `orders_add`
- `credit.calculate_score` → `credit_calculate_score`

## Input schema

Action payload валидируется через Pydantic-модель из `ActionMetadata.input_model`:

```python
# source: src/backend/entrypoints/mcp/mcp_server.py:82-98
schema = _action_input_schema_json(action_name)
# → metadata.input_model.model_json_schema()
```

## Per-tool authorization (Block 1.4, ADR-0072)

При `tool_authz_enabled=True` действует fail-closed политика:

```python
# source: src/backend/entrypoints/mcp/mcp_server.py:179-215
def _check_mcp_tool_authz(action_name: str) -> str | None:
    # 1. tool_authz_enabled=False → allow
    # 2. action в tool_allowlist → allow
    # 3. namespace в tool_public_namespaces → allow
    # 4. иначе → deny
```

## Регистрация кастомных namespaces

Для добавления business-specific tools используйте namespace-модуль:

```python
# src/backend/entrypoints/mcp/namespaces/credit_mcp.py
from fastmcp import FastMCP

def register_credit_namespace(mcp: FastMCP) -> None:
    @mcp.tool(name="credit_check", description="Кредитная проверка")
    async def credit_check(ssn: str, amount: float) -> str:
        ...
```

Вызов из `create_mcp_server()` или в startup-lifespan.

## Вызов через smpc CLI

```bash
# Список всех tools
smcp tools list

# Выполнить tool
smcp tools call orders_add --payload '{"customer_id": "C-123", "amount": 5000}'

# Проверить health
smcp tools call system_health
```

## Feature flags

| Flag | Default | Описание |
|------|---------|----------|
| `tool_authz_enabled` | `False` | Fail-closed per-tool authz |
| `legacy_description_schema` | `False` | Дублировать schema в description |
| `mcp_http_enabled` | `True` | HTTP transport |
| `mcp_stdio_enabled` | `True` | STDIO transport |

Настройки — `src/backend/core/config/ai_2026.py::mcp_settings`.

## Тестирование

```bash
python -c "
from src.backend.entrypoints.mcp.mcp_server import create_mcp_server
mcp = create_mcp_server()
print(f'MCP server created: {mcp}')
print(f'Available tools: {len(mcp._tool_manager._tools)}')
"
```

## См. также

- `src/backend/entrypoints/mcp/mcp_server.py` — полная реализация
- `src/backend/entrypoints/mcp/workflow_tools.py` — workflow tools
- `docs/tutorials/08_outbound_http_client.md` — WAF policy