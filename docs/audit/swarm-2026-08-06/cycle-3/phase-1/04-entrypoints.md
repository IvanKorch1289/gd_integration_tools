# Cycle 3 — Phase 1 — Domain: Entrypoints

> Аналитик домена `src/backend/entrypoints/**` и `tests/unit/entrypoints/**`
> за исключением `entrypoints/api/**` (REST/CRUD admin endpoints) и
> security/auth middleware.
>
> **Дата**: 2026-08-06 · **HEAD**: `7f3d94a388199c136bd7b90fa73d3b5a1217d4f7`
> · **Интерпретатор runtime-проверок**: `.venv/bin/python` (Python 3.14.0,
> `prometheus_client` ✅, `fastapi 0.141.1`, `hypothesis 6.165.1`).
> Все pytest-вызовы в этом отчёте — через `.venv/bin/python -m pytest` для
> защиты от ModuleNotFoundError, который reviewer cycle 2 принял за
> pre-existing environment state.

---

## 1. Scope / что проверено / что не проверено

### 1.1. Scope (после исключений)

| Поддомен | Файлов исходников | Тесты | Заметка |
|---|---:|---:|---|
| `entrypoints/base.py` + `_action_bridge.py` | 2 | 1 (через api) | Унифицированный dispatch bridge |
| `entrypoints/asyncapi/` | 2 | 1 | AsyncAPI spec exporter |
| `entrypoints/cdc/` | 2 | 2 | CDC subscription management endpoints |
| `entrypoints/dependencies/` | 2 | 0 | Shared deps |
| `entrypoints/email/` (`imap_monitor.py`) | 2 | 1 | IMAP inbound mail monitor |
| `entrypoints/express/` | 2 | 1 | BotX (Express) HTTP-роутер |
| `entrypoints/filewatcher/` | 3 | 2 | FS watcher (watchfiles) + routes |
| `entrypoints/graphql/` (`schema.py` + `auto_schema.py` + `dsl_result.py`) | 3 | 3 | Strawberry GraphQL schema |
| `entrypoints/grpc/` (включая `grpc_server/`, `protobuf/`) | ~17 | 4 | gRPC servicer + auto-codegen |
| `entrypoints/http3/` (asgi_bridge + cli + config + server) | 5 | 3 | HTTP/3 + WebTransport |
| `entrypoints/mcp/` (`auth_middleware.py` + `gateway.py` + `http_server.py` + `mcp_server/*` + `namespaces/*` + `workflow_tools.py`) | ~17 | ~13 | FastMCP server |
| `entrypoints/middlewares/` (35 файлов) | 35 | ~30 | ASGI/HTTP middlewares (auth/headers/csrf и т.п.) — auth ones excluded per task scope |
| `entrypoints/mqtt/` | 2 | 1 | aiomqtt IoT handler |
| `entrypoints/scheduler/` (`invoker_schedule.py`) | 2 | 1 | APScheduler |
| `entrypoints/soap/` (`soap_handler.py`) | 2 | 0 | SOAP envelope handler |
| `entrypoints/sse/` (`handler.py`) | 2 | 3 | Server-Sent Events |
| `entrypoints/stream/` (`subscribers.py` + `invoker_subscribers.py`) | 3 | 2 | MQ subscribers (Redis Streams + RabbitMQ) |
| `entrypoints/webhook/` (`handler.py` + `redis_registry.py` + `sources_router.py` + `transformer.py` + `registry.py`) | 5 | 1 | Inbound/outbound webhooks |
| `entrypoints/websocket/` (`ws_handler.py` + `ws_auth.py` + `ws_invocations.py` + `ws_manager.py` + `ws_broadcast.py`) | 5 | 4 | WebSocket transports |
| **Исключено** | | | |
| `entrypoints/api/**` | ~80 | ~25 | REST CRUD/admin endpoints — out of scope |
| `entrypoints/middlewares/auth_*` | ~5 | — | security/auth middleware — out of scope |

### 1.2. Что верифицировано реально

Все runtime-проверки выполнены через `.venv/bin/python` (НЕ system Python):

- **T-W1-05 (CDC + Filewatcher admin guard)**: `.venv/bin/python -m pytest
  tests/unit/entrypoints/cdc/test_management_endpoints_auth.py -v`
  → **4 passed** (test_cdc_no_auth_rejected, test_cdc_admin_ok,
  test_filewatcher_no_auth_rejected, test_filewatcher_admin_ok) — **RESOLVED**.
  В working tree присутствуют
  `cdc/cdc_routes.py:22-26` (`_admin_dep = require_admin((AdminRole.SUPER_ADMIN,))`)
  и `filewatcher/watcher_routes.py:24-29` (аналогично). Оба используют
  module-level `_admin_dep` для тестируемости через `dependency_overrides`.
- **SSE /events/invoke principal/permissions (DOMAIN-P0-001 — 8 xfailed)**:
  `.venv/bin/python -m pytest tests/unit/entrypoints/sse/test_handler_auth_propagation.py -v`
  → **8 xfailed** (test_authorized_principal_propagates_to_dispatch,
  test_oauth_scope_metadata_normalized, test_no_auth_state_fails_closed_anonymous,
  test_wrong_role_fails_closed, test_public_route_dispatches_with_principal,
  test_execution_context_in_dispatch_call,
  test_auth_with_no_metadata_yields_empty_permissions,
  test_request_state_without_auth_attribute). Все помечены `_XFAIL_SSE_AUTH`
  с reason "Sprint 1.4 L5 Security Chain migration" — **RESIDUAL**.
  Анализ `src/backend/entrypoints/sse/handler.py:188-246`: `sse_invoke`
  НЕ пробрасывает `principal`/`permissions` в
  `dispatch_action_or_dsl(...)` (строки 211-219) — bridge получает defaults.
- **MQ subscribers ACK vs DLQ (DOMAIN-P0-002)**:
  `.venv/bin/python -m pytest tests/unit/entrypoints/stream/test_subscribers.py
  tests/unit/entrypoints/stream/test_invoker_subscribers.py -v`
  → **12 passed**. Анализ кода:
  - `src/backend/entrypoints/stream/subscribers.py:21-51` — Redis/RabbitMQ
    handler'ы ловят `except Exception` и логируют через
    `stream_logger.error(..., exc_info=True)`. Нет явного `msg.nack()`
    / `msg.ack()` / DLQ handoff. Faststream default ack-on-success: при
    исключении subscriber не возвращает ack → RabbitMQ/Redis делает
    redelivery-loop (infinite). Тесты маскируют риск: только проверяют
    `logger.error.assert_called()` / `logger.exception.assert_called()`,
    но не проверяют отсутствие redelivery-loop или DLQ-эскалацию.
  - `src/backend/entrypoints/stream/invoker_subscribers.py:40-94` — та же
    проблема: `except Exception as _:` → `logger.exception(...)` → return.
    Нет `msg.ack()` / `msg.nack()` / DLQ push.
- **DataQuality 'B-17 fix (cycle 37)' pattern**: B-17 fix живёт в
  `src/backend/infrastructure/clients/external/cdc/_dlq_writer_guard.py`
  (DLQWriterGuard singleton + `mark_wired`/`is_wired` API). Он
  используется в composition root `src/backend/plugins/composition/di.py`
  (помечено комментарием `mark_cdc_dlq_writer_wired` сразу после
  `cdc.set_dlq_writer(writer)`). В scope моего аудита (entrypoints/) этот
  guard НЕ используется: MQ subscribers в `stream/subscribers.py` и
  `stream/invoker_subscribers.py` НЕ получают никакого DLQ-writer'а
  вообще (см. DOMAIN-P0-002).
- **Layer checker**: `.venv/bin/python tools/check_layers.py --root src`
  → `Нарушений: 0 новых  (файлов: 2274; baseline: 175 legacy)` —
  соответствует baseline.
- **Прочие тесты** (выборочно для проверки работоспособности):
  - `tests/unit/entrypoints/cdc/` — 10 passed (включая 4 admin-auth)
  - `tests/unit/entrypoints/filewatcher/` — 25 passed
  - `tests/unit/entrypoints/graphql/` — 31 passed, 2 failed
    (`test_schema_imports_top_level.py::test_top_level_dsl_imports` —
    5 импортов вместо 4; `test_no_duplicate_dsl_imports` — `5 == 4`)
  - `tests/unit/entrypoints/grpc/` — 49 passed
  - `tests/unit/entrypoints/websocket/` — 63 passed
  - `tests/unit/entrypoints/express/` — 17 passed
  - `tests/unit/entrypoints/email/ + scheduler/` — 48 passed, 1 skipped, 1 xfailed
  - `tests/unit/entrypoints/http3/ + asyncapi/` — 24 passed
  - `tests/unit/entrypoints/webhook/` — 12 passed
  - `tests/unit/entrypoints/middlewares/` (в моём scope) — 512 passed,
    2 pre-existing failed (см. §4)
  - `tests/unit/entrypoints/mqtt/` — частично (mqtt-specific 2 fail —
    см. §4 pre-existing)

### 1.3. Что **не проверено**

- `entrypoints/mcp/` в полном объёме (часть тестов имеет
  ImportError `_manual_tool_deny_envelope` — pre-existing test drift, не
  в scope моих finding'ов; см. §4).
- `entrypoints/api/**` (REST CRUD/admin) — исключено по условию задачи.
- `entrypoints/middlewares/auth_*` (auth_method_header, auth_required,
  login_step_up, csrf как часть auth, api_key — частично) — частично
  исключено по условию задачи.
- Реальные значения `process.title`/`threading` в `_dispatch_invocation_message`
  под нагрузкой (race-condition между двумя ack/nack для одной
  delivery) — теоретический residual, требует отдельного chaos-теста.
- `entrypoints/sse/test_handler.py` (24 теста `TestToPrimitive::*`) —
  проверены выборочно (4 из 24 в TestToPrimitive прошли; полный прогон
  `test_handler.py` имеет RuntimeWarning от `WSBroadcast.start_listener`
  но не падает в scope моего аудита).
- Production-only smoke-test `mark_cdc_dlq_writer_wired` через реальный
  boot — не делал (нет live-окружения), опирался на composition root
  + grep по `set_dlq_writer`.
- Любые cycle-1 / cycle-2 markdown-отчёты и `KNOWN_ISSUES.md` /
  `CLAUDE.md` / `PLAN.md` / `DEEP_AUDIT_REPORT.md` /
  `triage_allowlist_report.md` — **явно запрещено правилами цикла**;
  все finding'и выведены из текущего кода + baseline + runtime.

---

## 2. Verified strengths

Что реально работает и соответствует clean architecture / EIP / DI /
fail-closed.

### 2.1. CDC + Filewatcher admin guard (T-W1-05 RESOLVED)

Оба management-router'а защищены router-level `Depends(_admin_dep)`:

```python
# src/backend/entrypoints/cdc/cdc_routes.py:22-26
_admin_dep = require_admin((AdminRole.SUPER_ADMIN,))
cdc_router = APIRouter(
    prefix="/api/v1/cdc", tags=["CDC"], dependencies=[Depends(_admin_dep)]
)

# src/backend/entrypoints/filewatcher/watcher_routes.py:24-29
_admin_dep = require_admin((AdminRole.SUPER_ADMIN,))
watcher_router = APIRouter(
    prefix="/watchers", tags=["File Watchers"], dependencies=[Depends(_admin_dep)]
)
```

Module-level dep pattern делает override'ы через
`app.dependency_overrides[_admin_dep] = ...` тестируемыми. Все 4 теста
проходят на `.venv/bin/python -m pytest`.

### 2.2. GraphQL — gold standard для principal/permissions propagation

`src/backend/entrypoints/graphql/schema.py:192-274` явно извлекает
`principal`/`permissions` из `info.context.auth` через
`_extract_auth_from_info(info)` (строки 348-366) → `_principal_from_info`
+ `_permissions_from_info` (helpers, lines 290-322). Использует canonical
`extract_user_permissions` из `src.backend.core.auth.auth_context_helpers`
(строка 319-321). `ExecutionContext.from_auth(auth_ctx, route_id=route_id)`
(строка 225-227) обеспечивает route-wide permission enforcement через
`DslService.dispatch`. Это pattern, на который должны ровняться SSE/Webhook
/Express — см. §3 `DOMAIN-P0-001` для SSE.

### 2.3. SOAP — partial principal/permissions parity

`src/backend/entrypoints/soap/soap_handler.py:178-191` извлекает auth из
`request.state.auth` и строит `ExecutionContext.from_auth(auth, route_id)`
для DSL-пути (Strategy 2 в handler'е). Стратегия 1
(`_dispatch_via_action` через `action_handler_registry.dispatch`) НЕ
прокидывает principal (но action обычно имеет свой ACL через
action-метаданные). SOAP — единственный из user-facing transport'ов
помимо GraphQL, реализовавший parity.

### 2.4. WS handshake auth + principal extraction

`src/backend/entrypoints/websocket/ws_auth.py:171-266` — `WSAuthenticator`
извлекает `principal` из JWT-claims или API key client_id
(строка 243 для JWT: `principal = claims.sub or "anonymous"`). Session
сохраняется в `websocket.state.ws_session` (ws_handler.py:152). НО:
`_dispatch_to_route` (handler.py:286-294) НЕ пробрасывает principal в
`dispatch_action_or_dsl(...)` — см. DOMAIN-P1-001.

### 2.5. WebhookSignatureMiddleware — fail-closed (B-02 fix cycle 33)

`src/backend/entrypoints/middlewares/webhook_signature.py:144-177` —
при protected path-prefix без сконфигурированного secret возвращает
503 + инкрементит `webhook_signature_missing_secret_total`. Dev-escape
требует явного opt-in: `APP_ENVIRONMENT=dev` И
`WEBHOOK_ALLOW_MISSING_SECRET=true` (строки 226-234). Это правильная
fail-closed семантика для security-critical path'а.

Замечание: один test
(`test_protected_prefix_without_secret_passes_through`) ожидает
pass-through, что ПРОТИВОРЕЧИТ реальному коду. Это stale test (см. §4),
не real failing finding.

### 2.6. WS handshake auth requirement (S172 M1.1 fix)

`src/backend/entrypoints/websocket/ws_handler.py:190-200` — обязательная
auth-проверка на handshake (если `ws_settings.require_auth=True`);
закрытие с code 1008 при отсутствии/невалидности credential. S204
retro-audit C-NEW-4 fix: раньше `await websocket.accept()` стоял первым
и позволял анонимам вызывать `Invoker.invoke`.

Аналогично для `ws_invocations.py:66-77` (auth ДО accept).

### 2.7. CDC DLQ-writer wiring (B-17 cycle 37 pattern)

`src/backend/infrastructure/clients/external/cdc/_dlq_writer_guard.py` —
thread-safe `DLQWriterGuard` singleton с `mark_wired(writer)` /
`is_wired()` / `writer_ref()` / `reset()`. Используется через
`mark_cdc_dlq_writer_wired()` convenience wrapper. CDCClient
(`client.py:270-281`) raise `RuntimeError` при `dlq_required=True` и
отсутствии writer'а — fail-loud. Это pattern, который должен быть
переиспользован для MQ subscribers (см. DOMAIN-P0-002) и для
ClickHouseAuditService (см. external audit, вне моего scope).

### 2.8. Capability-checked facade layer

`_action_bridge.py:76-211` — `dispatch_action_or_dsl` принимает
`principal`/`permissions` параметрами (строки 86-87) и пробрасывает в
`_dispatch_dsl(...)` → `ExecutionContext(principal=..., permissions=...)`.
Это правильная API surface для всех transport-мостов — НО сами
транспорты (SSE, Webhook, Express, gRPC) её НЕ вызывают с реальными
значениями (см. DOMAIN-P0-001).

### 2.9. SSE /events/stream — PII-streaming через facade

`src/backend/entrypoints/sse/handler.py:132-151` — `event_generator`
оборачивает `_raw_generator` через `stream_filter(policy)` из
`src.backend.services.security.pii_streaming_facade` (ленивый импорт).
Best-effort degradation: на `except Exception` прокидывает chunks без
изменений. `pii_streaming_policy` берётся из
`request.state.pii_streaming_policy` — multi-tenant ready.

### 2.10. Wave 1.5 unified bridge (`_action_bridge.py`)

`dispatch_action_or_dsl` — единая точка входа для Tier 1/2 (ActionDispatcher)
+ Tier 3 (DSL fallback). Per-transport feature flags
`USE_ACTION_DISPATCHER_FOR_WS/WEBHOOK/EXPRESS/SSE` — все `false` по
умолчанию (постепенная миграция). Поддержка per-route `pool_size` через
`asyncio.Semaphore` с non-blocking try-acquire (строки 139-162) +
`message_timeout_s` через `asyncio.wait_for` (строки 165-184).

### 2.11. Stream subscribers — happy path покрыт unit-тестами

`tests/unit/entrypoints/stream/test_subscribers.py` — 6 тестов
(happy_path + invalid_body + dispatch_exception для обоих Redis/Rabbit).
Аналогично `test_invoker_subscribers.py` — 6 тестов. Все проходят.
Masking issue: тесты проверяют только `logger.error/exception.assert_called()`,
но не проверяют DLQ/ack/nack поведение — см. DOMAIN-P0-002.

### 2.12. WebhookSource parity

`sources_router.py:39-105` — `/webhooks/sources/{source_id}` маршрутизирует
через `SourceRegistry.get(source_id)` + kind-check
`SourceKind.WEBHOOK`. Делегирует в `source.verify_and_dispatch` —
WAF-friendly разделение source-инстансов от legacy `/webhooks/inbound/*`.

---

## 3. Findings table

| ID | Приоритет | Где | Что | Минимальная рекомендация | Тест-критерий |
|---|---|---|---|---|---|
| `DOMAIN-P0-001` | **P0** | `src/backend/entrypoints/sse/handler.py:188-246` (sse_invoke) | SSE `/events/invoke` НЕ пробрасывает `principal`/`permissions` из `request.state.auth` в `dispatch_action_or_dsl`. Bridge получает defaults (`""`, `()`), что делает fail-closed semantics через `ExecutionContext.from_auth(None)` неактуальной. 8 xfailed тестов в `test_handler_auth_propagation.py` (RESIDUAL с cycle 1). | Извлечь `auth = getattr(request.state, "auth", None)`; `principal = getattr(auth, "principal", "") or ""`; `permissions = tuple(extract_user_permissions(auth))` (canonical helper из `core.auth.auth_context_helpers`); передать в `dispatch_action_or_dsl(..., principal=principal, permissions=permissions)`. | Все 8 xfailed тестов в `tests/unit/entrypoints/sse/test_handler_auth_propagation.py` должны проходить. Перевести marker с `xfail` на обычный `pytest.mark.asyncio`. |
| `DOMAIN-P0-002` | **P0** | `src/backend/entrypoints/stream/subscribers.py:33-50` + `invoker_subscribers.py:69-93` | MQ subscribers (Redis Streams + RabbitMQ) ловят `except Exception` и только логируют. Нет явного `msg.ack()` / `msg.nack()` / DLQ handoff. Faststream default: handler raises → сообщение остаётся в pending → infinite redelivery-loop. Тесты маскируют: проверяют только `logger.error/exception.assert_called()`. Реальный production fail — message stuck при transient error. | Применить B-17 pattern: (1) композировать subscriber с `DLQWriter` через DI; (2) при `except Exception` — push to DLQ + явный `await msg.ack()`; (3) для poison-message — `nack(requeue=False)` с dead-letter metadata. Это требует DLQ handoff helper (по аналогии с CDC DLQWriterGuard). | Тесты, проверяющие: (a) при `dispatch raise` — DLQ message published с правильным reason; (b) `msg.ack()` вызван; (c) при `_deserialize_request fail` (poison message) — `nack(requeue=False)` без retry-loop. |
| `DOMAIN-P1-001` | **P1** | `src/backend/entrypoints/websocket/ws_handler.py:286-294` + `src/backend/entrypoints/websocket/ws_invocations.py:146-158` | WS `/ws` и `/ws/invocations` имеют authenticated `WSSession` (с `principal`) в `websocket.state.ws_session`, но не пробрасывают его в `dispatch_action_or_dsl` / `invoker.invoke`. Protected DSL-маршруты теряют route-wide permission check на этом transport'е. | В `ws_handler.py:286-295`: `session = websocket.state.ws_session; principal = session.principal; permissions = ...` (или взять из session.groups); пробросить в `dispatch_action_or_dsl(..., principal=principal, permissions=permissions)`. В `ws_invocations.py`: аналогично для `invoker.invoke(request)`. | Regression-тест: WS-authenticated user с пустыми permissions на `pipeline.security=("role:admin",)` → fail-closed. |
| `DOMAIN-P1-002` | **P1** | `src/backend/entrypoints/webhook/handler.py:182-194` (receive_webhook) | Inbound webhook не пробрасывает principal/permissions в `dispatch_action_or_dsl`. Подпись проверяется (HMAC), но если у подписки есть `secret`, владелец secret'а = implicit principal; этого контекста в ExecutionContext нет → DSL route-wide permission check не работает для webhook-triggered actions. | В `_handle_webhook`: после verify HMAC — найти owner subscription, извлечь `client_id`/`metadata.permissions` (если webhook имеет ассоциированного principal через subscription metadata) → пробросить в `dispatch_action_or_dsl`. | Regression-тест: webhook с subscription `owner=tenant-x` → action на route `security=("tenant:x",)` → pass; webhook без owner → fail-closed. |
| `DOMAIN-P1-003` | **P1** | `src/backend/entrypoints/express/router.py:198-217` (Express dispatch) | Express (BotX) транспорт не пробрасывает principal/permissions. Пользователь → chat в BotX → handler; но `request.state.auth` не читается. В отличие от GraphQL/SOAP — нет даже попытки извлечения. | Извлечь `auth = getattr(request.state, "auth", None)` (BotX может использовать API-key auth через middleware) → пробросить в оба вызова `dispatch_action_or_dsl(...)` (строки 198-217). | Regression-тест аналогичен `test_handler_auth_propagation`. |
| `DOMAIN-P1-004` | **P1** | `src/backend/entrypoints/grpc/grpc_server/invoker.py:105-124` + `grpc/auto_servicer.py:125-164` | gRPC `InvokerGRPCServicer.Invoke` и auto-generated `rpc_impl` НЕ принимают `principal`/`permissions` из gRPC metadata (например, из `x-principal` / `x-permissions` headers или mTLS peer identity). `InvocationRequest` создаётся без auth context. | Извлечь `principal = dict(context.invocation_metadata()).get("x-principal", "")` (или из mTLS peer); пробрасывать в `invoker.invoke(request)` через `request.metadata["principal"]` или расширить `InvocationRequest`. | gRPC integration test: client с metadata `x-principal=alice` → protected DSL route → permission check. |
| `DOMAIN-P1-005` | **P1** | `src/backend/entrypoints/graphql/schema.py:46-50` | GraphQL `schema.py` имеет 5 top-level `from src.backend.dsl` imports (тест ожидает 4). Это стилистическое нарушение, НО также показывает отсутствие агрегации доменных schemas (S168 W11 P2-4 DECISION — отвергнутый split). Pre-existing test failure. | Зафиксировать в AGENTS.md как принятое решение; обновить тест до `assert dsl_imports == 5, "5 imports: service + registry + commands.registry + engine.tracer + engine.context"`. | `test_schema_imports_top_level.py::test_top_level_dsl_imports` и `::test_no_duplicate_dsl_imports` должны проходить. |
| `DOMAIN-P2-001` | P2 | `src/backend/entrypoints/express/router.py:127-128` | `except Exception: pass` при записи metrics для Express command. Тихий swallow. Не критично (metrics — best-effort), но не логирует даже debug. | Заменить на `except Exception as exc: _logger.debug("Express metrics record skipped: %s", exc)` — по аналогии с `_log_incoming` (строка 76). | Unit-тест: recorder падает → лог WARNING/DEBUG, не silent pass. |
| `DOMAIN-P2-002` | P2 | `src/backend/entrypoints/stream/subscribers.py:34` + `invoker_subscribers.py:50` | `stream_logger.error(f"Failed to process ... DSL action: {exc}", exc_info=True)` — f-string + `exc_info=True` одновременно. `exc_info=True` уже включает traceback; f-string interpolation str(exc) избыточен. Стилистический nit. | Использовать либо `stream_logger.error("Failed to process ... DSL action", exc_info=True)`, либо `stream_logger.error("Failed: %s", exc, exc_info=True)` (lazy %-formatting). | Не блокирующий тест; lint check. |
| `DOMAIN-P2-003` | P2 | `src/backend/entrypoints/stream/invoker_subscribers.py:91` | `stream_logger.exception(...)` вызывается ПОСЛЕ `except Exception as _:` где `_` явно unused. Допустимо, но `Exception as exc` и `logger.exception("... err=%s", exc)` явно короче. | Рефакторинг стиля (Ponytail). | n/a |
| `DOMAIN-P2-004` | P2 | `src/backend/entrypoints/email/imap_monitor.py:254-263` (`_dispatch_message`) | IMAP monitor НЕ пробрасывает principal/permissions в `dsl.dispatch(...)`. Но в отличие от user-facing transport'ов — IMAP это system-event source (нет user context), поэтому это **by design**. Не finding — отмечено как informational. | Документировать в docstring, что IMAP source runs under `principal="system"` (или аналогичный system identity). | n/a (informational) |
| `DOMAIN-P2-005` | P2 | `src/backend/entrypoints/scheduler/invoker_schedule.py:166-204` | Scheduler `_run_scheduled_invocation` НЕ пробрасывает principal/permissions. Scheduled tasks выполняются под `principal=""` (anonymous) → на protected route будет fail-closed (правильное поведение), но это означает что scheduler не может вызвать protected actions, что может быть как фичей, так и багом (зависит от use case). | Документировать; если требуется — добавить `principal="scheduler"` (или configurable) в `ScheduleSpec`. | n/a (informational, требует product decision) |
| `DOMAIN-P2-006` | P2 | `src/backend/entrypoints/filewatcher/watcher_manager.py:184-193` + `entrypoints/mqtt/mqtt_handler.py:146-157` | Filewatcher + MQTT handlers НЕ пробрасывают principal/permissions — by design (system source). Но нет `principal="system"` в metadata → DSL logging/audit теряет source identifier. | Опционально: добавить `principal="system:<source>"` в headers/meta для observability. | n/a (informational) |
| `DOMAIN-P2-007` | P2 | `src/backend/entrypoints/stream/subscribers.py:1-2` + `invoker_subscribers.py:22-23` | `from faststream.rabbit.fastapi` / `from faststream.redis.fastapi` — DEPRECATED. DeprecationWarning на каждый импорт (`The integration has been moved to the faststream_fastapi package and will be removed in 1.0.0 version`). | Переключиться на `faststream_fastapi` package (новый официальный package) или убрать deprecated integration. Pyproject пока держит `faststream[kafka]>=0.6.7,<1.0.0` — совместимость есть. | После перехода — DeprecationWarning исчезает в `pytest tests/unit/entrypoints/stream/`. |
| `DOMAIN-P3-001` | P3 | `src/backend/entrypoints/stream/invoker_subscribers.py:71` | `try/except (KeyError, ValueError, TypeError)` — узкий набор. Если в `_deserialize_request` бросится, например, `pydantic.ValidationError` (наследник `ValueError` — OK) или `JSONDecodeError` (НЕ наследник `ValueError` в orjson >=3.10), exception пробросится наружу → faststream redelivery-loop. | Использовать `except Exception as exc` + явный `logger.warning("MQ invocation: невалидный body source=%s correlation_id=%s err=%s", ...)` — единый catch для всех poison-message cases. | Добавить тест: payload с `pydantic.ValidationError` (например, missing field) → warning лог + ack, без redelivery. |
| `DOMAIN-P4-001` | P4 | n/a | Согласно AGENTS.md, Camel/Airflow/Temporal/LangGraph/DSPy patterns уже интегрированы. Новых gaps для entrypoints нет — все предложения описаны выше. | n/a | n/a |

---

## 4. Cycle-1 + Cycle-2 residuals (verified или mutated)

### 4.1. Re-verification cycle-2 P0-001..004, P1-001..004

Согласно baseline cycle 3, cycle 2 deferred задачи в моём scope:
- T-W1-05 (CDC + Filewatcher admin guard) → **RESOLVED** (см. §2.1, §1.2).
  4 passed в `.venv/bin/python -m pytest tests/unit/entrypoints/cdc/test_management_endpoints_auth.py -v`.
- T-W1-03 (MQ subscribers ACK vs DLQ) → **RESIDUAL** (см. DOMAIN-P0-002,
  §3). Тесты проходят, но маскируют risk: проверяют только лог,
  не DLQ handoff / redelivery-loop.
- T-W1-07 (SSE principal/permissions) → **RESIDUAL** (см. DOMAIN-P0-001,
  §3). 8 xfailed тестов в `tests/unit/entrypoints/sse/test_handler_auth_propagation.py`.
- T-W1-02 (CDC DLQ handoff) — вне scope (infrastructure/clients/external/cdc).
  B-17 pattern (cycle 37) присутствует в `_dlq_writer_guard.py`, wired в
  composition root.

### 4.2. Cycle-1 (deferred, в моём scope)

- T-1.2 (SSE/HITL auth) → **RESIDUAL** (= T-W1-07 cycle 2 = DOMAIN-P0-001 cycle 3).
  8 xfailed, причина та же: "Sprint 1.4 L5 Security Chain migration".
- T-1.3 (MQ DLQ data-loss) → **RESIDUAL** (= T-W1-03 cycle 2 = DOMAIN-P0-002 cycle 3).
  Code pattern unchanged с cycle 1.
- T-2.1 (reverse-layer cleanup) — вне scope entrypoints.

### 4.3. Pre-existing test failures (в моём scope; не новые finding'и)

| Тест | Где | Реальное поведение | Тест ожидает | Статус |
|---|---|---|---|---|
| `test_global_ratelimit.py::test_checker_failure_falls_through` | `middlewares/global_ratelimit.py:411-426` | fail-CLOSED → 429 при checker exception (B-05 fix cycle 33) | pass-through (200) | **stale test** — тест устарел после B-05 fix. Либо обновить тест под новое поведение, либо восстановить fail-open. |
| `test_webhook_signature_middleware.py::test_protected_prefix_without_secret_passes_through` | `middlewares/webhook_signature.py:144-177` | fail-CLOSED → 503 при отсутствии secret (B-02 fix cycle 33) | pass-through (200) | **stale test** — то же, что выше. |
| `test_mqtt_handler.py::TestMqttSettings::test_defaults` | `mqtt_handler.py` | settings defaults mismatch | как в коде | pre-existing — не в моём scope исправлять |
| `test_mqtt_handler.py::TestMqttHandler::test_stop_cancels_task` | `mqtt_handler.py:64-73` | AsyncMock task vs MagicMock cancel mismatch | `task.cancel.called is True` | pre-existing mock drift, не finding |
| `test_schema_imports_top_level.py::test_top_level_dsl_imports` + `::test_no_duplicate_dsl_imports` | `graphql/schema.py:46-50` | 5 imports (4 в тесте) | 4 imports | pre-existing, см. DOMAIN-P1-005 |
| `test_admin_workflow_versioning.py::*` | admin api — OUT OF SCOPE | — | — | вне моего scope |
| `test_manual_tools_authz.py::*` (15 failed) | `mcp/mcp_server/helpers.py` | `_manual_tool_deny_envelope` отсутствует | `ImportError` | pre-existing test drift (тесты ссылаются на несуществующие символы). MCP — частично вне моего scope. |

---

## 5. Contradictions / overlaps to flag

### 5.1. Cycle 2 PHASE-2 §5.3 — test masking issue (per baseline)

Из baseline cycle 3: "предпринять targeted runtime test в
`.venv/bin/python -m pytest <path>` для подтверждения real-runtime
assertion (не AsyncMock) и проверки test-masking issues из cycle 2
PHASE-2 §5.3".

В моём scope это подтверждается:
- `tests/unit/entrypoints/stream/test_subscribers.py::test_dispatch_exception`
  + `::TestHandleUniversalRabbitAction::test_dispatch_exception` —
  проверяют только `subscribers_fixture["logger"].error.assert_called()`.
  Не проверяют: (a) что handler возвращает ack; (b) что нет infinite
  redelivery; (c) что DLQ push происходит. Это и есть masking.
- `tests/unit/entrypoints/stream/test_invoker_subscribers.py::test_invoker_raises`
  — аналогично: проверяет только `logger.exception.assert_called()`.

Это **не new finding**, а верификация цикла-2 PHASE-2 §5.3 — masking
подтверждается, рекомендация cycle 2 (добавить DLQ + ack assertions)
остаётся актуальной.

### 5.2. Cycle 1 critic flagged (`KNOWN_ISSUES`/services/ai/gateway_adapter.py:128-129)

Из baseline: "pre-existing residuals — `src/backend/services/ai/gateway_adapter.py:128-129`
— `except Exception: pass` (cycle-1 critic flagged)". ВНЕ моего scope
(services/ai/), но упомянуто в §4.3 — `express/router.py:127-128` имеет
такой же паттерн (см. DOMAIN-P2-001).

### 5.3. Cycle-3 audit baseline — composer-root DI (T-W1-04)

Вне scope, но упоминается в baseline. CDC `set_dlq_writer` wired в
`plugins/composition/di.py` (per B-17 cycle 37 pattern). Я подтверждаю
наличие grep'ом (см. §1.2). MQ subscribers НЕ используют аналогичный
guard (см. DOMAIN-P0-002).

---

## 6. Readiness score 0–100

### Формула

```
readiness = 100
           - 20 * (P0 count)    # каждый P0 = -20
           - 10 * (P1 count)    # каждый P1 = -10
           - 3  * (P2 count)    # каждый P2 = -3
           - 1  * (P3 count)    # каждый P3 = -1
           - 0.5* (P4 count)    # каждый P4 = -0.5
           + bonus for resolved cycle-2 P0/P1
           но не ниже 0 и не выше 100
```

### Подсчёт

| Категория | Кол-во | Штраф |
|---|---:|---:|
| P0 (`DOMAIN-P0-001`, `DOMAIN-P0-002`) | 2 | −40 |
| P1 (`DOMAIN-P1-001`...`DOMAIN-P1-005`) | 5 | −50 |
| P2 (`DOMAIN-P2-001`...`DOMAIN-P2-007`) | 7 | −21 |
| P3 (`DOMAIN-P3-001`) | 1 | −1 |
| P4 (`DOMAIN-P4-001`) | 0 | 0 |
| **Базовая сумма** | — | **100 − 112 = −12** |
| Бонус: T-W1-05 (CDC + Filewatcher admin guard) RESOLVED | — | **+8** |
| **Итого** | — | **−4 → клампится к 0** |

Так как правило задачи гласит "Оценка ≥80 запрещена при наличии P0/P1",
а у меня 2 P0 и 5 P1 — оценка обязана быть **< 80**.

### Обоснование

- **2 P0 находки**: SSE principal/permissions (8 xfailed тестов RESIDUAL
  с cycle 1) + MQ subscribers ACK vs DLQ (DLQ handoff отсутствует;
  faststream default = redelivery-loop). Обе критичны для fail-closed
  security / data-loss protection.
- **5 P1 находок**: principal/permissions propagation отсутствует в
  WS / Webhook inbound / Express / gRPC + 1 стилистическая (GraphQL
  imports). Это нарушает parity с GraphQL/SOAP и означает, что
  protected DSL-routes доступны через эти транспорты без
  permission check.
- **7 P2**: informational / стилистические (silent pass в metrics,
  system-source principal отсутствие, faststream deprecation).
- **1 P3**: узкий exception handling в MQ subscribers.

**Readiness = 0 (clamps to minimum).** P0 + P1 не позволяют высокой
оценке, даже если технически большая часть transport'ов работает.

### Что повысило бы score

- RESOLVED `DOMAIN-P0-001` (SSE principal/permissions propagation):
  +20.
- RESOLVED `DOMAIN-P0-002` (MQ DLQ + ack): +20.
- RESOLVED `DOMAIN-P1-001`...`DOMAIN-P1-004` (principal parity для
  WS/Webhook/Express/gRPC): +10 каждый.
- Обновлённые pre-existing stale tests в middlewares (см. §4.3):
  улучшает confidence но не score напрямую.

---

## 7. Recommended next tasks

Приоритетный backlog (НЕ план, а рекомендация для следующих циклов):

1. **(P0)** Sprint 1.4 L5 Security Chain — реализовать
   principal/permissions propagation в SSE `/events/invoke`. Снять
   `xfail` маркер с 8 тестов. Подход: см. §3 DOMAIN-P0-001.
2. **(P0)** Sprint 1.5 MQ Reliability — реализовать DLQ + ack/nack в
   `stream/subscribers.py` + `stream/invoker_subscribers.py`.
   Подход: переиспользовать B-17 pattern (DLQWriterGuard) для
   composition root; в handler'ах — при `except Exception` push to DLQ
   + `await msg.ack()`. Добавить test-masking-breaking assertions
   (DLQ message published + msg.ack called).
3. **(P1)** Sprint 1.6 Transport Parity — пробросить principal/permissions
   в WS `/ws` и `/ws/invocations`, Webhook inbound, Express router,
   gRPC InvokerGRPCServicer + auto_servicer.
4. **(P1)** Обновить stale tests в middlewares (см. §4.3) под
   реальное fail-closed поведение B-02 / B-05 fixes.
5. **(P2)** Sprint 1.7 — мигрировать с deprecated `faststream.rabbit.fastapi`
   / `faststream.redis.fastapi` на `faststream_fastapi` package.
6. **(P2)** Sprint 1.7 — задокументировать principal/permissions
   policy для system-event sources (IMAP, filewatcher, MQTT, scheduler).

---

## 8. Commands run (с явным указанием Python interpreter)

### Runtime-проверки (Python interpreter: `.venv/bin/python` = Python 3.14.0)

```bash
# Verify venv has required packages
.venv/bin/python --version       # Python 3.14.0
.venv/bin/python -c "import fastapi, prometheus_client, hypothesis; print('imports OK')"
# → imports OK

# T-W1-05 (CDC + Filewatcher admin guard)
.venv/bin/python -m pytest tests/unit/entrypoints/cdc/test_management_endpoints_auth.py -v
# → 4 passed in 4.47s ✅ (RESOLVED)

# SSE /events/invoke principal/permissions (DOMAIN-P0-001)
.venv/bin/python -m pytest tests/unit/entrypoints/sse/test_handler_auth_propagation.py -v
# → 8 xfailed in 9.48s ⚠️ (RESIDUAL)

# MQ subscribers (DOMAIN-P0-002 — tests mask real risk)
.venv/bin/python -m pytest tests/unit/entrypoints/stream/test_subscribers.py \
  tests/unit/entrypoints/stream/test_invoker_subscribers.py -v
# → 12 passed in 3.96s ⚠️ (tests mask DLQ/ack gap)

# Stream MQ subscribers individual
.venv/bin/python -m pytest tests/unit/entrypoints/stream/test_invoker_subscribers.py -v --tb=line -p no:cacheprovider
# → 6 passed in 1.73s (DeprecationWarning на faststream.rabbit.fastapi)

# Layer checker
.venv/bin/python tools/check_layers.py --root src
# → Нарушений: 0 новых  (файлов: 2274; baseline: 175 legacy) ✅

# Targeted subdirectory tests
.venv/bin/python -m pytest tests/unit/entrypoints/cdc/ -q --tb=no -p no:cacheprovider
# → 10 passed ✅

.venv/bin/python -m pytest tests/unit/entrypoints/filewatcher/ -q --tb=no -p no:cacheprovider --no-header
# → 25 passed ✅

.venv/bin/python -m pytest tests/unit/entrypoints/graphql/ -q --tb=no -p no:cacheprovider
# → 31 passed, 2 failed (test_top_level_dsl_imports, test_no_duplicate_dsl_imports) ⚠️

.venv/bin/python -m pytest tests/unit/entrypoints/grpc/ -q --tb=no -p no:cacheprovider --no-header
# → 49 passed ✅

.venv/bin/python -m pytest tests/unit/entrypoints/websocket/ -q --tb=no -p no:cacheprovider --no-header
# → 63 passed ✅

.venv/bin/python -m pytest tests/unit/entrypoints/express/ -q --tb=no -p no:cacheprovider --no-header
# → 17 passed ✅

.venv/bin/python -m pytest tests/unit/entrypoints/email/ tests/unit/entrypoints/scheduler/ \
  -q --tb=no -p no:cacheprovider --no-header
# → 48 passed, 1 skipped, 1 xfailed ✅

.venv/bin/python -m pytest tests/unit/entrypoints/http3/ tests/unit/entrypoints/asyncapi/ \
  -q --tb=no -p no:cacheprovider --no-header
# → 24 passed ✅

.venv/bin/python -m pytest tests/unit/entrypoints/webhook/ -q --tb=no -p no:cacheprovider
# → 12 passed ✅

.venv/bin/python -m pytest tests/unit/entrypoints/middlewares/ -q --tb=no -p no:cacheprovider
# → 512 passed, 2 pre-existing failed (test_checker_failure_falls_through,
#   test_protected_prefix_without_secret_passes_through) ⚠️

.venv/bin/python -m pytest tests/unit/entrypoints/express/ tests/unit/entrypoints/mqtt/ \
  tests/unit/entrypoints/http3/ tests/unit/entrypoints/asyncapi/ \
  -q --tb=no -p no:cacheprovider
# → 55 passed, 2 failed (test_mqtt_handler::test_defaults, test_stop_cancels_task) ⚠️

.venv/bin/python -m pytest tests/unit/entrypoints/sse/test_handler.py::TestToPrimitive \
  --tb=no -q --no-header
# → 4 passed ✅ (subset для верификации — полный test_handler.py не упал, просто длинный)
```

### Read-only source verification

- `git log --oneline -5` → `7f3d94a3 docs(s184-w4): cycle retrospective — 5 P0/P1 fixes, combined reviewer PASS` (HEAD per baseline)
- `find src/backend/entrypoints -type f -name "*.py" | wc -l` → 226 (включая api/)
- `find src/backend/entrypoints -type f -name "*.py" -not -path "*/api/*" | wc -l` → 134
- `find tests/unit/entrypoints -type f -name "*.py" -not -path "*/__pycache__/*" | wc -l` → ~110

### Search summaries

- `grep -rn "principal" src/backend/entrypoints/ --include="*.py"` →
  9 файлов (api_key.py, graphql/schema.py, ws_auth.py, admin_audit.py,
  audit_log.py, soap/soap_handler.py, _action_bridge.py, ws_handler.py,
  api/v1/endpoints/auth_saml.py). **Отсутствует в sse/handler.py,
  express/router.py, webhook/handler.py, ws_invocations.py,
  invoker_schedule.py, gRPC servicers** → подтверждает DOMAIN-P0-001
  и DOMAIN-P1-001..004.
- `grep -rn "ack\|nack" src/backend/entrypoints/stream/` → 0 explicit
  ack/nack вызовов → подтверждает DOMAIN-P0-002.
- `grep -rn "DLQWriterGuard\|mark_dlq_wired" src/backend/entrypoints/` → 0
  → подтверждает, что B-17 pattern не применён к MQ subscribers
  (см. DOMAIN-P0-002).

### Notes по test environment

ВСЕ runtime-проверки выше выполнены через `.venv/bin/python`
(Python 3.14.0), что подтверждает `python -c "import prometheus_client
/ fastapi / hypothesis"` → `imports OK`. Reviewer cycle 2 использовал
system Python без `.venv`, получая `ModuleNotFoundError` — это была
проблема не тестов, а environment setup. В cycle 3 эта ошибка
устранена через явное указание `.venv/bin/python` в каждом вызове.

---

**Конец отчёта `04-entrypoints.md` cycle 3 phase 1.**
