# Architecture Map — аудит a2bd6f294 (2026-09-30)

## Масштаб
6769 tracked файлов | 774k LOC | 2771 production py | 2263 test py | 3844 модулей графа | 11346 рёбер.

## Слои (фактические)
- entrypoints/ — REST (api/v1, 30+ роутеров), GraphQL, gRPC, SOAP, streams (FastStream), MCP, WS/SSE, middlewares (38 шт., order 10-880).
- services/ — use cases: execution (invoker/modes), scheduler (facade/run_history/backfill), workflow, ops, integrations, billing, notebooks, ai.
- core/ — домен, DI providers (http/ai/cache/...), config (pydantic-settings, 30+ модулей), feature_flags, tenancy, security (object_ownership, pii), net (WAF), messaging (eventbus), workflow_registry.
- infrastructure/ — клиенты (redis wrapper, s3 pool, smtp, mongo), DB (initializer, async engine, Continuum), scheduler (APScheduler manager, TemporalSchedulerBackend, Lite/PG runner), workflow (temporal_backend, compensating_driver, factories), secrets (Vault), observability.
- dsl/ — ядро: engine (processors ~60, execution_engine 403 LOC), builders (RouteBuilder god-MRO 76 классов), registry, workflow (compiler/emitter, yaml_io), blueprints.
- extensions/ — бизнес-плагины (credit_pipeline и др.).
- frontend/streamlit_app/ — портал (36+ страниц).
- tests/ — 2263 файлов (unit/integration/smoke/chaos/property).

## Импортный граф: 16 SCC (циклических компонент)
1. **649 модулей** — гигантский компонент: core.ai.* ↔ core.config ↔ services ↔ entrypoints.api ↔ plugins.composition (main↔app_factory↔routers↔admin_plugins...). Фактически «ядро-монолит».
2. services.ops.data_quality (6) — self-referential mixin-пакет.
3. entrypoints.api.v1.endpoints.admin_plugins ↔ routers ↔ main ↔ app_factory (6).
+13 мелких (2-5 модулей).

## Точки входа runtime
- granian/uvicorn ← main.py (create_app, APP_WORKERS), lifespan → STARTUP_PHASES (observability/infrastructure/services) → run_startup.
- grpc serve (отдельный entrypoint), stream-подписчики (module-import декораторы faststream).

## Найденные структурные дефекты (top)
- SCC-649: цикл main↔app_factory↔routers↔endpoints (см. import_graph.json sccs_multi_node[0]).
- entrypoints middleware LIFO-инверсия: policy-middlewares (rpa_policy 720, ai_tool_whitelist 640) работают ДО auth (620) при комментарии «after auth».
- DSL builders: god-MRO 76 + дубли CollectionMixin/RequestReplyMixin вне MRO.
