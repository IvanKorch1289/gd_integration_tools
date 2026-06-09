# Итерация 3: Фронтенд и API

## 3.1 Фронтенд — 6/10
**Плюсы:** Streamlit 65+ страниц, PAGES_GROUPS.toml, feature flags pages, CORS/retry/WS/SSE backend integration, API clients с retry.
**Минусы:** Streamlit flat structure (65 файлов в одной папке), числовые префиксы в URL, `BaseAPIClient` синхронный (блокирует Streamlit), `Realtime_Logs` хак с threading. React MVP на mock-данных (2 компонента, нет auth, нет тестов). Нет поиска по страницам. React не использует WS/SSE.

## 3.2 API Entrypoints — 8/10
**Плюсы:** REST 40+ routers, FastAPI DI, auto-REST (Wave 1.2), gRPC 8 proto + auto-servicer, GraphQL Strawberry + subscriptions, SOAP WSDL auto, WS/SSE/MQTT, MCP 50+ tools, Webhook HMAC, FileWatcher, Email IMAP, Scheduler APScheduler, CDC REST. Auth 7 методов + middleware registry 25+ в 4 слоях. OAuth2 introspection, SAML SSO.
**Минусы:** v2 API мёртв (versioning.py есть, но get_v2_routers() не существует). gRPC только unary, нет reflection. GraphQL нет federation. SOAP WSDL string-only. WS без auth на handshake. BASIC auth — dummy (только parse, не verify). MQTT без tenant propagation.

## 3.3 Multi-protocol обработка — 7/10
**Плюсы:** Единый dispatch_action, ActionHandlerRegistry, 6 InvocationMode, proto_adapter хороший, strawberry_adapter хороший, auto-servicer/auto-schema.
**Минусы:** XML не standalone (только в SOAP). SOAP — ручная строковая склейка XML. GraphQL generic JSON scalar — теряет типизацию. Нет perf-бенчмарков cross-protocol. ASYNC_QUEUE/DEFERRED частично заглушены. Нет unit-тестов SOAP/XML parsing и MQTT routing. ActionRouterBuilder раздут (~1000 строк).

## 3.4 OpenAPI и схемы — 6/10
**Плюсы:** ServiceSchemaRegistry lock-free, 3 формата экспорта, AsyncAPI 3.0, DSL migration framework (BFS apiVersion), import gateway OpenAPI→ConnectorSpec.
**Минусы:** FastAPI использует стандартный json.dumps вместо orjson. DSL openapi_generator выдаёт generic `type: object`. Нет merged OpenAPI (FastAPI native + schema_registry отдельно). Нет Postman export. Versioning middleware написан, но не подключён.

## 3.5 Security entrypoints — 5/10
**Плюсы:** Defense-in-depth архитектура, 7 auth методов, audit logging, tenant middleware, CORS валидатор.
**Минусы (критичные):** APIKeyMiddleware (order 110) ломает per-client ключи — проверяет только статический глобальный ключ. GlobalRateLimitMiddleware НЕ зарегистрирован в setup_middlewares. SecurityHeadersMiddleware (HSTS/CSP) не подключён. Audit log не знает кто вызвал (client_id не проставляется). SQLAlchemyRepository НЕ фильтрует по tenant_id автоматически. BlockedRoutesMiddleware — exact match, не ловит подпути. Нет входящего WAF.

## Библиотеки из web search
- `fastapi_multiprotocol_004` — универсальный middleware для REST/JSON-RPC/SOAP/gRPC
- `strawberry.experimental.pydantic` — генерация GraphQL типов из Pydantic
- Streamlit 1.36+ `st.Page` + `st.navigation` — замена числовых префиксов
