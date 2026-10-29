# Tutorials

Step-by-step learning paths (Diátaxis tutorial quadrant): от «простой
роут» до workflow, RAG и MCP.

```{toctree}
:maxdepth: 1

00_getting_started
01_build_first_action
01_first_route
02_first_plugin
03_route_hot_reload
04_temporal_workflow
05_hitl_workflow
06_streamlit_dashboard
07_rag_pipeline
08_outbound_http_client
09_dlq_replay
10_token_budget
11_clickhouse_audit
12_mcp_server
13_service_dsl
14_routebuilder_python_api
15_dependency_injection
```

## Learning path

| # | Туториал | Что даёт |
|---|---|---|
| 00 | [Getting started](00_getting_started.md) | Старт окружения, hello-world. |
| 01 | [Build first action](01_build_first_action.md) | Первый action в `ActionDispatcher`. |
| 01 | [First route](01_first_route.md) | Первый DSL-роут. |
| 02 | [First plugin](02_first_plugin.md) | Плагин с `plugin.toml` и capability. |
| 03 | [Route hot reload](03_route_hot_reload.md) | Перезагрузка роутов без рестарта. |
| 04 | [Temporal workflow](04_temporal_workflow.md) | Workflow с XOR/AND gateway, запуск через admin-API. |
| 05 | [HITL workflow](05_hitl_workflow.md) | Workflow с approval-сигналом. |
| 06 | [Streamlit dashboard](06_streamlit_dashboard.md) | Портал разработчика. |
| 07 | [RAG pipeline](07_rag_pipeline.md) | Индексация и retrieval. |
| 08 | [Outbound HTTP client](08_outbound_http_client.md) | Исходящие HTTP-вызовы с ретраями. |
| 09 | [DLQ replay](09_dlq_replay.md) | Разбор и повтор DLQ. |
| 10 | [Token budget](10_token_budget.md) | Квоты токенов на tenant. |
| 11 | [ClickHouse audit](11_clickhouse_audit.md) | Доставка audit-событий в ClickHouse. |
| 12 | [MCP server](12_mcp_server.md) | MCP-сервер проекта. |
| 13 | [Service DSL](13_service_dsl.md) | Авто-CRUD сервисов. |
| 14 | [RouteBuilder Python API](14_routebuilder_python_api.md) | Fluent API роутов. |
| 15 | [Dependency injection](15_dependency_injection.md) | DI-провайдеры и фасады. |

## Терминология

**Шаг** (step) — одна декларация в `steps[]` workflow; **этап** (stage) —
крупная фаза из нескольких шагов. В коде есть только шаги. См.
[Workflows → Терминология](../workflows/index.md#терминология).
