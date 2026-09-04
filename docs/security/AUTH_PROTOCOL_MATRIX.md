# AUTH_PROTOCOL_MATRIX — auth-покрытие по протоколам (17 entrypoints)

> **Дата**: 2026-09-05. Задача DOCS1 (`docs/roadmap/PROGRESS_LEDGER.md`, закрытие мёртвой ссылки M5-#9 из `PRODUCTION_READINESS_FINAL.md`).
> **Метод**: grep по `src/backend/entrypoints/` (require_admin, AuthRequiredMiddleware, HMAC, ws_auth, AuthInterceptor, auth_middleware, require_auth) + функциональные пробы M6-#3 (негативный auth 401 на живом инстансе, 2026-09-04).
> **Итог M5-#9**: auth-покрытие закрыто по факту — 13 протоколов с HTTP/соединительной поверхностью имеют auth, 4 (scheduler, email, asyncapi, stream-специфика) работают без HTTP-поверхности или на брокерных credentials.

## Матрица

| # | Протокол | Каталог | Auth-механизм | Доказательство (файл:строка) | Статус |
|---|---|---|---|---|---|
| 1 | REST (api) | `api/` | Глобальный `AuthRequiredMiddleware` (order 620) + per-route `require_auth` (API_KEY/JWT) через auth_selector | `entrypoints/middlewares/setup_middlewares.py:204`; `entrypoints/api/dependencies/auth_selector.py` | ЗАКРЫТ |
| 2 | GraphQL | `graphql/` | `_graphql_context_getter` + propagation principal/permissions из `request.state.auth` (require_auth middleware) | `entrypoints/graphql/schema.py:49,80-89` | ЗАКРЫТ (401 без токена, M6-#3) |
| 3 | gRPC | `grpc/` | `AuthInterceptor` (grpc.aio.ServerInterceptor, header `authorization`) | `entrypoints/grpc/grpc_server/interceptor.py:24,51-55` | ЗАКРЫТ |
| 4 | SOAP | `soap/` | `require_auth([API_KEY, JWT])` на роутере + auth context в meta dispatch | `entrypoints/soap/soap_handler.py:30,143-160,177` | ЗАКРЫТ (401, M6-#3) |
| 5 | WebSocket | `websocket/` | `ws_auth` facade — 3 механизма: query-token, cookie `auth_session`, header (JWT/API-key) | `entrypoints/websocket/ws_auth.py:1-18,40` | ЗАКРЫТ (401, M6-#3) |
| 6 | SSE | `sse/` | `require_auth([API_KEY, JWT])` на endpoint + `extract_user_permissions` (fail-closed без auth) | `entrypoints/sse/handler.py:24-25,107,182-191` | ЗАКРЫТ (401, M6-#3) |
| 7 | Webhook | `webhook/` | Inbound: HMAC + timestamp (`verify_and_dispatch`); management CRUD: `require_auth` | `infrastructure/sources/webhook.py:104,176`; `entrypoints/webhook/handler.py:36-40`; `entrypoints/webhook/sources_router.py:87-88` | ЗАКРЫТ (401, M6-#3) |
| 8 | Stream (MQ) | `stream/` | Брокерные credentials (Redis Streams / RabbitMQ из settings); без HTTP-поверхности | `entrypoints/stream/invoker_subscribers.py:1-9` | ЗАКРЫТ (вне HTTP-auth) |
| 9 | MQTT | `mqtt/` | Брокерные credentials (`settings.password`); message_timeout/backpressure (W3 `37156dbdb`) | `entrypoints/mqtt/mqtt_handler.py:120,231` | ЗАКРЫТ (вне HTTP-auth) |
| 10 | MCP | `mcp/` | `McpAuthMiddleware` wrap FastMCP ASGI app (S49 W1, defense-in-depth restored) | `entrypoints/mcp/http_server.py:112-121` | ЗАКРЫТ (401, M6-#3) |
| 11 | CDC | `cdc/` | `require_admin((AdminRole.SUPER_ADMIN,))` на уровне router | `entrypoints/cdc/cdc_routes.py:16,24` | ЗАКРЫТ (M5-#9) |
| 12 | FileWatcher | `filewatcher/` | `require_admin((AdminRole.SUPER_ADMIN,))` на уровне router | `entrypoints/filewatcher/watcher_routes.py:16,25` | ЗАКРЫТ (M5-#9) |
| 13 | Scheduler | `scheduler/` | Без HTTP-поверхности: APScheduler CronTrigger/IntervalTrigger → Invoker (cron-триггеры, не внешний вход) | `entrypoints/scheduler/invoker_schedule.py:1-10` | N/A (cron-триггеры) |
| 14 | Email | `email/` | Без HTTP-поверхности: IMAP credentials (`password_vault_ref`; явный `password` — только dev) | `entrypoints/email/imap_monitor.py:9-10,40-41` | N/A (IMAP creds) |
| 15 | Express | `express/` | Глобальный `AuthRequiredMiddleware` (без локального auth в BotX-роутере) | `entrypoints/express/router.py:1-20`; `middlewares/setup_middlewares.py:204` | ЗАКРЫТ |
| 16 | HTTP/3 | `http3/` | ASGI-bridge: события aioquic.h3 → ASGI-scope, запрос проходит общую middleware-цепочку (вкл. auth_required) | `entrypoints/http3/asgi_bridge.py:1-8` | ЗАКРЫТ (через общий стек) |
| 17 | AsyncAPI | `asyncapi/` | Экспортёр спецификации FastStream-брокеров; runtime-эндпоинтов нет, auth не применим | `entrypoints/asyncapi/exporter.py:1-8` | N/A (spec-only) |

## Легенда статусов

- **ЗАКРЫТ** — auth-механизм присутствует в коде (доказательство файл:строка); для HTTP-протоколов дополнительно негативная проба 401 (M6-#3, 2026-09-04, живой инстанс dev_light).
- **N/A** — протокол без HTTP-поверхности (брокер/IMAP/cron/spec): HTTP-auth не применим, доступ контролируется инфраструктурными credentials.

## Ограничения

- Позитивные JWT-сценарии (step-up login) и брокерные протоколы (MQTT/MQ в docker) — остаток M6-#3, см. `PROGRESS_LEDGER.md` §M6.
- express: BotX callback-подпись не верифицируется на уровне роутера — вход закрыт глобальным `AuthRequiredMiddleware`; вынесено как наблюдение (не P0/P1).
