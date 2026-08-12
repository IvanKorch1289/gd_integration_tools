# Entrypoints domain audit — cycle 2 / phase 1

- **Date:** 2026-08-06
- **HEAD:** `ca5bff93058f2580041a7339913b52943babb329`
- **Scope:** `src/backend/entrypoints/**` (исключая `entrypoints/api/**` и
  security/auth middleware в `entrypoints/middlewares/{auth_*, *_auth.py,
  api_key.py, csrf.py, login_step_up.py, auth_method_header.py, rpa_policy.py,
  webhook_signature*.py, blocked_routes.py}`) и `tests/unit/entrypoints/**` для
  перечисленных файлов, плюс `entrypoints/base.py`, `entrypoints/_action_bridge.py`,
  `entrypoints/dependencies/rate_limit.py`, `entrypoints/cdc/**`, `entrypoints/email/**`,
  `entrypoints/express/**`, `entrypoints/filewatcher/**`, `entrypoints/graphql/**`,
  `entrypoints/grpc/**`, `entrypoints/http3/**`, `entrypoints/mcp/**`, `entrypoints/mqtt/**`,
  `entrypoints/scheduler/**`, `entrypoints/soap/**`, `entrypoints/sse/**`,
  `entrypoints/stream/**`, `entrypoints/webhook/**`, `entrypoints/websocket/**`,
  `entrypoints/asyncapi/**`, `entrypoints/dependencies/**`, `entrypoints/__init__.py`.
- **Out of scope:** `entrypoints/api/**` (отдельный отчёт 05-api.md);
  security/auth middleware (отдельный отчёт 02-security.md).
- **Baseline (cycle 2):** commit `ca5bff93`; layer checker `python tools/check_layers.py --root src`
  → **0 новых / 175 legacy** (2273 файлов); `wc -l tools/check_layers_allowlist.txt` = **180 строк
  (5 комментариев + 175 entry-строк)** — расхождение с "ростом 173→180" из задания: реальное
  число нарушений **не выросло** (175 = 175), пользовательская формулировка "180" относится
  к line-count файла, не к количеству entry; `pip-audit-allowlist.txt` = **35** активных
  CVE/GHSA/PYSEC ID. Pre-existing `M uv.lock` (-15 svcs), `M tools/blue_green.sh`,
  `M tests/unit/tools/test_blue_green_switch.py`, `?? pip-audit.json`, `?? .blue_green.state`,
  5 uncommitted source правок cycle 1 Phase 4 (T-1.4 / T-1.5 / T-3.1) — НЕ атрибутируются рою cycle 2
  и не трогались.
- **Найдено:** 12 finding (4 P0, 4 P1, 2 P2, 2 P3, 0 P4). Все cycle-1 IDs из задания
  (DOMAIN-P0-001, DOMAIN-P0-002, P1-001) перепроверены в коде `ca5bff93` и помечены
  RESIDUAL/MUTATED с явным evidence.

---

## 1. Scope / что проверено / что не проверено

### 1.1 Проверено (по файлам)

| Файл / артефакт | Прочитано | Примечание |
|---|---|---|
| `src/backend/entrypoints/_action_bridge.py` | да | целиком — критический bridge |
| `src/backend/entrypoints/base.py` | да | целиком — `dispatch_action` + `BaseEntrypoint` (deprecated per S171 M10) |
| `src/backend/entrypoints/asyncapi/exporter.py` | да | целиком |
| `src/backend/entrypoints/cdc/cdc_routes.py` | да | целиком (P0-кандидат: нет auth) |
| `src/backend/entrypoints/email/imap_monitor.py` | да | целиком |
| `src/backend/entrypoints/express/router.py` | да | целиком |
| `src/backend/entrypoints/filewatcher/watcher_manager.py` | да | целиком |
| `src/backend/entrypoints/filewatcher/watcher_routes.py` | да | целиком (P0-кандидат: нет auth) |
| `src/backend/entrypoints/graphql/schema.py` | да | целиком (parity-pattern) |
| `src/backend/entrypoints/grpc/grpc_server/invoker.py` | да | целиком |
| `src/backend/entrypoints/http3/server.py` | да | целиком |
| `src/backend/entrypoints/mcp/mcp_server/__init__.py` | да | целиком |
| `src/backend/entrypoints/mcp/mcp_server/tools_route.py` | да | целиком (DSL access без principal) |
| `src/backend/entrypoints/mcp/mcp_server/tools_yaml.py` | да | целиком |
| `src/backend/entrypoints/mqtt/mqtt_handler.py` | да | целиком (P0-кандидат: нет auth, нет DLQ) |
| `src/backend/entrypoints/scheduler/invoker_schedule.py` | да | целиком |
| `src/backend/entrypoints/soap/soap_handler.py` | да | целиком (parity-pattern: `from_auth`) |
| `src/backend/entrypoints/sse/handler.py` | да | целиком (DOMAIN-P0-001) |
| `src/backend/entrypoints/stream/subscribers.py` | да | целиком (P1-001 + DOMAIN-P0-002) |
| `src/backend/entrypoints/stream/invoker_subscribers.py` | да | целиком (DOMAIN-P0-002) |
| `src/backend/entrypoints/webhook/handler.py` | да | целиком (нет principal) |
| `src/backend/entrypoints/websocket/ws_handler.py` | да | целиком (нет principal) |
| `src/backend/entrypoints/websocket/ws_auth.py` | да | целиком (WSSession.principal, но не проброшен) |
| `src/backend/entrypoints/websocket/ws_invocations.py` | да | целиком |
| `src/backend/entrypoints/websocket/ws_manager.py` | да | целиком |
| `src/backend/dsl/service/facade.py` | да | целиком (`DslService.dispatch` + `_enforce_route_permission`) |
| `src/backend/dsl/engine/context.py` | да | целиком (`ExecutionContext.from_auth`) |
| `src/backend/dsl/commands/registry.py` | да | целиком |
| `src/backend/core/auth/auth_context_helpers.py` | да | целиком (`extract_user_permissions`) |
| `src/backend/infrastructure/messaging/dlq_base.py` | да | целиком (DLQWriter protocol) |
| `src/backend/infrastructure/clients/external/cdc/_dlq_writer_guard.py` | да | целиком (B-17 fix reference) |
| `tests/unit/entrypoints/sse/test_handler_auth_propagation.py` | да | целиком (8 xfail — DOMAIN-P0-001 evidence) |
| `tests/unit/entrypoints/mcp/test_mcp_no_dsl_principal_propagation.py` | да | целиком (2 FAILED — API mismatch) |
| `tests/unit/entrypoints/stream/test_subscribers.py` | да | целиком |
| `tests/unit/entrypoints/test_base.py` | да | целиком (7 PASS) |
| `tools/check_layers_allowlist.txt` | да (wc -l) | 180 строк = 5 коммент + 175 entry |
| Layer checker output | да | exit 0, 0 new / 175 legacy |

### 1.2 Не проверено

- `entrypoints/grpc/grpc_server/{base,file_stream,interceptor,order,server,_safe_error}.py`,
  `entrypoints/grpc/auto_servicer.py`, `entrypoints/grpc/correlation.py`,
  `entrypoints/grpc/proto_viewer.py` — **не проверено** (за пределами прямого scope
  задания; основной grpc.servicer-flow покрыт через `invoker.py` и `correlation.py` —
  последний упомянут косвенно). Если потребуется — отдельный audit.
- `entrypoints/mcp/{http_server,gateway,input_schema_resolver,mcp_server/{tools_*,helpers}.py,
  namespaces/*.py, workflow_tools.py}` — не читались целиком, проверены только публичные
  контракты и `_register_route_tools` (parity с DSL).
- `entrypoints/websocket/ws_broadcast.py` — **не проверено** (вне прямого scope cycle 2).
- `entrypoints/scheduler/invoker_schedule.py` — прочитан целиком, но scheduler-tick не
  относится к MQ/MQTT-ack-логике, и в нём используется `action_handler_registry.dispatch`
  (Tier 1/2 path, не DSL). Не считаю находкой.
- `entrypoints/http3/{asgi_bridge,cli,config,_protocol}.py` — не читались (HTTP/3 transport,
  не заявлен в задании; базовая `server.py` проверена, выглядит чисто).
- `entrypoints/asyncapi/__init__.py`, `entrypoints/email/__init__.py`,
  `entrypoints/cdc/__init__.py`, `entrypoints/mqtt/__init__.py`, `entrypoints/sse/__init__.py`,
  `entrypoints/stream/__init__.py`, `entrypoints/soap/__init__.py`, `entrypoints/express/__init__.py`,
  `entrypoints/webhook/__init__.py`, `entrypoints/websocket/__init__.py`,
  `entrypoints/__init__.py` — marker-only, проверены через `wc -l` / `cat`.
- `entrypoints/dependencies/rate_limit.py` — не проверено (вне прямого scope; относится
  к shared-deps layer).
- Pre-existing uncommitted правки (cycle 1 Phase 4 T-1.4 / T-1.5 / T-3.1) в
  `core/ai/gateway_pipeline_mixin/policy_mixin.py`, `dsl/engine/processors/eip/{reliability,multicast}.py`,
  `infrastructure/cache/rag/embedding_cache.py`, `services/ai/gateway_adapter.py` и
  соответствующих тестах — **НЕ в scope этого домена** (entrypoints), не атрибутируются
  рою cycle 2.

---

## 2. Verified strengths

| ID | Strength | Evidence |
|---|---|---|
| S-E1 | **Parity-паттерн для principal/permissions через `ExecutionContext.from_auth`** корректно реализован в SOAP | `src/backend/entrypoints/soap/soap_handler.py:178-192` — `auth = getattr(request.state, "auth", None); context = ExecutionContext.from_auth(auth, route_id=route_id)`. Fail-closed: `from_auth(None)` → `principal=""` + `permissions=()`. |
| S-E2 | **GraphQL полностью поддерживает parity-паттерн** (principal + permissions + scope-normalization через `extract_user_permissions`) | `src/backend/entrypoints/graphql/schema.py:225-227,252-274,290-321,348-366,442-458,541-558`. Sprint 1.1 parity с REST/SOAP — комментарии и реализация согласованы. |
| S-E3 | **`_action_bridge.dispatch_action_or_dsl` имеет сигнатуру с `principal`/`permissions` kwargs** (Sprint 1.1), но все entrypoint-callsite'ы НЕ пробрасывают их — найден как contract в DSL-layer | `src/backend/entrypoints/_action_bridge.py:76-114` (docstring), `86-87` (parameters), `170-181, 184-192` (passed in `_dispatch_dsl`). |
| S-E4 | **`extract_user_permissions` helper существует и нормализует OAuth scope → `scope:xxx`** (Sprint 1) | `src/backend/core/auth/auth_context_helpers.py:51-74`. Покрывает `metadata["permissions"]` (list) и `metadata["scope"]` (space-separated). |
| S-E5 | **WS auth на handshake обязательна** (S172 M1.1) | `src/backend/entrypoints/websocket/ws_handler.py:192-200` + `ws_invocations.py:67-77`. Закрытие с code 1008 при missing/invalid credential. |
| S-E6 | **WebSocket session содержит `principal` поле** | `src/backend/entrypoints/websocket/ws_auth.py:84,210,243,260-265`. |
| S-E7 | **PII streaming для SSE работает** (S13 K1 W1) | `src/backend/entrypoints/sse/handler.py:132-151` — `stream_filter` с per-tenant `PiiStreamPolicy`, fallback на raw-stream при ошибке. |
| S-E8 | **WebSocket per-action pool enforcement** (S163 W33) | `src/backend/entrypoints/websocket/ws_handler.py:217-231` — `route pool full` reject через `ws_manager.action_count`. |
| S-E9 | **WebSocket per-message timeout** (S163 W13) | `src/backend/entrypoints/websocket/ws_handler.py:253-267` — `asyncio.wait_for(websocket.receive_json(), timeout=ws_settings.message_timeout_s)`. |
| S-E10 | **DLQ infra (DLQEnvelope + DLQWriter protocol + DLQWriterGuard) существует** | `src/backend/infrastructure/messaging/dlq_base.py:30-117`, `src/backend/infrastructure/clients/external/cdc/_dlq_writer_guard.py:35-100`. B-17 fix (cycle 37) — fail-loud wiring. |
| S-E11 | **CDC `_dispatch_change` пишет в DLQ при exception** | `src/backend/infrastructure/clients/external/cdc/client.py:228,247` — `_send_to_dlq(envelope)` через `dlq_writer.write`. Fail-loud if `dlq_required=True` and writer not wired. |
| S-E12 | **MQ TTL + rate-limit на webhook** | `src/backend/entrypoints/webhook/handler.py:43-70` — `_check_rate_limit` per-client IP (100 req/min default). |
| S-E13 | **SOAP fault mapping корректно отделён от 200-OK** | `src/backend/entrypoints/soap/soap_handler.py:202-216` — `ValueError → 400 Client`, `KeyError → 404 Client`, `BaseError → exc.status_code`, generic → 500 Server. |
| S-E14 | **gRPC Invoker: error-safe serialization с correlation-id** | `src/backend/entrypoints/grpc/grpc_server/invoker.py:122-133` — `_safe_error(exc, cid)` скрывает stack-trace, лог сохраняется. |
| S-E15 | **MQTT TLS: VERIFY_CERT_REQUIRED, hostname-check on** | `src/backend/entrypoints/mqtt/mqtt_handler.py:84-95` — `ctx.check_hostname = True; ctx.verify_mode = ssl.CERT_REQUIRED`. |
| S-E16 | **IMAP пароль из Vault если указана `password_vault_ref`** (S179) | `src/backend/entrypoints/email/imap_monitor.py:115-130` — `vault_refresher.resolve(ref)`, fallback на `config.password` только при ошибке. |
| S-E17 | **FastStream deprecated-import warning замечен** (P3-кандидат) | `tests/unit/entrypoints/stream/test_subscribers.py:5-15` — `DeprecationWarning: The integration has been moved to the faststream_fastapi package and will be removed in 1.0.0`. 7 import-сайтов в `stream.py` + `subscribers.py` + `invoker_subscribers.py`. |
| S-E18 | **Streaming body hash helper (M5)** | `src/backend/entrypoints/middlewares/_streaming_hash.py` (упомянуто в AGENTS.md). Не открывал в этой фазе — out of scope. |
| S-E19 | **`BaseEntrypoint` помечен `@deprecated` per S171 M10** | `src/backend/entrypoints/base.py:99-103` — "определён, но НЕ наследуется ни одним протоколом. Реальная унификация идёт через свободную функцию `dispatch_action()`". |
| S-E20 | **WS `/ws/invocations` использует Invoker, не DslService** (правильный layer) | `src/backend/entrypoints/websocket/ws_invocations.py:158` — `await invoker.invoke(request)`. |
| S-E21 | **GraphQL `route_execute` MCP tool — bypass permission enforcement** (явный design) | `src/backend/entrypoints/mcp/mcp_server/tools_route.py:59-95` — `ExecutionEngine().execute(pipeline, body=parsed)` БЕЗ `ExecutionContext`. Зафиксировано в `test_mcp_no_dsl_principal_propagation.py:24-37` как by-design. |
| S-E22 | **CDC client DLQ integration + fail-loud wiring** (B-17) | `src/backend/infrastructure/clients/external/cdc/client.py:267-274` — `if not self._dlq_writer and self._dlq_required: raise RuntimeError`. Не атрибутируется к entrypoints, но в scope (CDC routes используют этот client). |

---

## 3. Findings table (P0..P4)

| ID | Priority | File:line | Краткое описание |
|---|---|---|---|
| DOMAIN-P0-001 (RESIDUAL) | P0 | `src/backend/entrypoints/sse/handler.py:188-219` (call-site); `src/backend/entrypoints/_action_bridge.py:86-87` (params) | SSE `/events/invoke` НЕ пробрасывает `principal`/`permissions` из `request.state.auth` в `dispatch_action_or_dsl` → `DslService.dispatch`. Bridge-сигнатура имеет kwargs, но caller не передаёт. 8/8 forward-looking TDD тестов в `test_handler_auth_propagation.py` остаются `xfail`. |
| DOMAIN-P0-002 (RESIDUAL) | P0 | `src/backend/entrypoints/stream/subscribers.py:21-34, 38-50`; `src/backend/entrypoints/stream/invoker_subscribers.py:40-94` | MQ Redis + RabbitMQ subscribers (DSL-action + Invoker) делают `except Exception: logger.error(...)` и ACK-сообщение (через FastStream default `auto_ack=True`). Никакого DLQ-enqueue через `DLQWriter`/`DLQEnvelope` — сообщение теряется безвозвратно. **B-17 fail-loud DLQ pattern НЕ применён** к новому MQ-коду (cycle 38+). |
| DOMAIN-P0-003 | P0 | `src/backend/entrypoints/cdc/cdc_routes.py:38-70`; `src/backend/entrypoints/filewatcher/watcher_routes.py:33-69` | Management endpoints (`POST/DELETE/GET /api/v1/cdc/subscriptions` и `POST/DELETE/GET /watchers/`) **БЕЗ `Depends(require_auth(...))`**. Контраст: `webhook/handler.py:84-127` защищён `Depends(_require_auth_dep)`. Неаутентифицированный клиент может: создать CDC-подписку (стартует callback-loop + DLQ-writes), удалить чужую подписку, создать filewatcher (триггерит DSL-route с произвольным body), удалить чужой watcher. **fail-open**. |
| DOMAIN-P0-004 | P0 | `src/backend/entrypoints/mqtt/mqtt_handler.py:131-157` | MQTT inbound `_handle_message` НЕ ВАЛИДИРУЕТ client identity / broker ACL / topic-pattern → вызывает `action_handler_registry.dispatch` напрямую без principal/permissions. **fail-open для всех MQTT-подписчиков** в production-режиме. Контраст: WS auth на handshake обязателен (S172 M1.1), но MQTT обходит это. |
| DOMAIN-P1-001 (RESIDUAL) | P1 | `src/backend/entrypoints/stream/subscribers.py:9` | `from src.backend.entrypoints.api.generator.registry import action_handler_registry` — re-export-через-API модуль. Канонический путь: `src.backend.dsl.commands.registry`. Этот же pattern зафиксирован в `tools/check_layers_allowlist.txt:src/backend/entrypoints/_action_bridge.py entrypoints src.backend.dsl.service` (legacy) и `:src/backend/entrypoints/email/imap_monitor.py entrypoints src.backend.dsl.service` (legacy) — почему-то `subscribers.py:9` не в allowlist (потенциальный незафиксированный нарушитель). Проверено: layer checker exit 0, 0 new — **видимо этот import считается allowed, т.к. `entrypoints.api.generator.registry` — `entrypoints→entrypoints` (допустимо в текущей политике)**. Тем не менее import через API — антипаттерн (ломает инвариант "entrypoints независимы друг от друга"). |
| DOMAIN-P1-002 | P1 | `src/backend/entrypoints/websocket/ws_handler.py:286-295`; `src/backend/entrypoints/webhook/handler.py:182-194`; `src/backend/entrypoints/express/router.py:198-217` | Эти 3 entrypoint-callsite'а `dispatch_action_or_dsl` НЕ передают `principal`/`permissions`. У них ЕСТЬ identity в момент dispatch (ws: `websocket.state.ws_session.principal`; webhook: `subscription.secret` → нет user; express: `payload["from"]["user_huid"]`). После исправления DOMAIN-P0-001 (через 8 xfail тестов) — должны последовать эти 3. |
| DOMAIN-P1-003 | P1 | `src/backend/entrypoints/mcp/mcp_server/tools_route.py:55-95` (`route_execute` tool) | Прямой вызов `ExecutionEngine().execute(pipeline, body=parsed)` **без `ExecutionContext`** — обходит `check_route_permission` (`DslService._enforce_route_permission`). Зафиксировано в `test_mcp_no_dsl_principal_propagation.py:24-37` как by-design (DSL-routes не экспонируются как MCP tools), но `route_execute` MCP tool ЯВНО вызывает `ExecutionEngine` напрямую — это формальный обход L5 security chain. |
| DOMAIN-P1-004 | P1 | `src/backend/entrypoints/email/imap_monitor.py:240-265`; `src/backend/entrypoints/filewatcher/watcher_manager.py:178-195` | IMAP + Filewatcher вызывают `dsl.dispatch` БЕЗ `context` (т.е. без `principal`/`permissions`). На protected routes это fail-closed (anonymous=deny), но логирует "anonymous" — ухудшает observability/auditability для system-events. |
| DOMAIN-P2-001 | P2 | `src/backend/entrypoints/base.py:90-145` (`BaseEntrypoint` class) | Класс помечен `@deprecated per S171 M10` (docstring строки 99-103), но **не удалён** — `test_base.py:62-89` использует `DummyEntrypoint(BaseEntrypoint)` для тестов. ~50 LOC мёртвого кода в `entrypoints/base.py`. |
| DOMAIN-P2-002 | P2 | `src/backend/entrypoints/sse/handler.py:96` (singleton `event_bus`); `src/backend/entrypoints/cdc/cdc_routes.py:38-70` (CRUD без TenantContext) | `event_bus` — module-level singleton с in-memory `asyncio.Queue(maxsize=100)`. На multi-worker deployment (uvicorn workers > 1) события не пересекают процессы. **Не dead code, но architectural limitation** — должно быть заменено на Redis-pubsub (EIP: `eventBus`/`publish-subscribeChannel`) для horizontal scaling. CDC-маршруты также не передают `tenant_id` (нет `Depends(tenant_dep)`), что нарушает per-tenant quotas. |
| DOMAIN-P3-001 | P3 | `src/backend/entrypoints/stream/subscribers.py:1-2`; `src/backend/entrypoints/stream/invoker_subscribers.py:22-23`; `src/backend/infrastructure/clients/messaging/stream.py:126,149,183` | `from faststream.{rabbit,redis,kafka}.fastapi import ...` — **DEPRECATED** в faststream 0.6+ (warning: "moved to faststream_fastapi package, will be removed in 1.0.0"). 7 import-сайтов. Replacement: `faststream_fastapi` (ещё не в pyproject). LOC delta: ~0 (drop-in). |
| DOMAIN-P3-002 | P3 | `src/backend/entrypoints/stream/subscribers.py:32, 47`; `src/backend/entrypoints/stream/invoker_subscribers.py:46, 53`; `src/backend/entrypoints/stream/invoker_subscribers.py:60-66` (docstring); `src/backend/entrypoints/mqtt/mqtt_handler.py:128` (manual reconnect) | Custom reconnect-логика (`asyncio.sleep(5)`, `_dispatch_invocation_message` + `except Exception` ack) — **может быть заменена `tenacity` retry-policy** (уже в `pyproject.toml`) или на `aio-pika` RobustConnection (для RabbitMQ). Сейчас нет max-retry / exponential-backoff — бесконечный retry на poison-message. Установленные библиотеки: `tenacity` (проверено — есть). LOC delta: -10..-20. |

---

## 4. Detailed evidence

### 4.1 DOMAIN-P0-001 — SSE `/events/invoke` не пробрасывает principal/permissions

**Evidence (read-only, точные цитаты):**

1. `src/backend/entrypoints/sse/handler.py:178-236` (полный `sse_invoke` endpoint):
   ```python
   @sse_router.post(
       "/invoke",
       ...
       dependencies=[Depends(require_auth([AuthMethod.API_KEY, AuthMethod.JWT]))],
   )
   async def sse_invoke(request: Request, body: _InvokeRequest) -> StreamingResponse:
       correlation_id = request.headers.get("x-correlation-id") or request.headers.get("x-request-id")
       idempotency_key = request.headers.get("idempotency-key")
       async def stream() -> Any:
           yield (f"event: start\ndata: {encode_json_str({'action': body.action})}\n\n")
           try:
               bridge = await dispatch_action_or_dsl(
                   action_id=body.action,
                   dsl_route_id=body.action,
                   payload=body.payload,
                   transport="sse",
                   correlation_id=correlation_id,
                   idempotency_key=idempotency_key,
                   attributes={"path": str(request.url.path)},
               )
   ```
   → **НЕТ `principal=` или `permissions=` kwargs**. `request.state.auth` НЕ извлекается.

2. `src/backend/entrypoints/_action_bridge.py:86-87`:
   ```python
   principal: str = "",
   permissions: tuple[str, ...] = (),
   ```
   → Defaults передаются в `ExecutionContext` (`_dispatch_dsl:262-263, 287-295`) →
   `DslService._enforce_route_permission` (`src/backend/dsl/service/facade.py:78`) →
   `principal = "anonymous"` → fail-closed **только** для protected routes (с
   `pipeline.security` непустым). На public routes — execute без permission check.

3. `src/backend/dsl/service/facade.py:62-90` — `_enforce_route_permission` читает
   `getattr(context, "principal", "")` → пустая строка → `"anonymous"` (line 78).
   `check_route_permission` (line 79) получает `principal="anonymous"`.

4. **TDD-тесты подтверждают**: `tests/unit/entrypoints/sse/test_handler_auth_propagation.py:50-57`
   ```python
   _XFAIL_SSE_AUTH = pytest.mark.xfail(
       reason=(
           "SSE /events/invoke не пробрасывает principal/permissions "
           "из request.state.auth в DslService.dispatch (parity с GraphQL/REST). "
           "Forward-looking TDD до Sprint 1.4 L5 Security Chain migration."
       ),
       strict=True,
   )
   ```
   Все 8 тестов помечены `xfail strict=True` — **тест ДОЛЖЕН fail** (т.е. функционал
   отсутствует). Прогон:
   ```
   $ .venv/bin/python -m pytest tests/unit/entrypoints/sse/test_handler_auth_propagation.py -v
   collected 8 items
   tests/unit/entrypoints/sse/test_handler_auth_propagation.py::TestSseAuthContextPropagation::test_authorized_principal_propagates_to_dispatch XFAIL
   tests/unit/entrypoints/sse/test_handler_auth_propagation.py::TestSseAuthContextPropagation::test_oauth_scope_metadata_normalized XFAIL
   tests/unit/entrypoints/sse/test_handler_auth_propagation.py::TestSseAuthContextPropagation::test_no_auth_state_fails_closed_anonymous XFAIL
   tests/unit/entrypoints/sse/test_handler_auth_propagation.py::TestSseAuthContextPropagation::test_wrong_role_fails_closed XFAIL
   tests/unit/entrypoints/sse/test_handler_auth_propagation.py::TestSseAuthContextPropagation::test_public_route_dispatches_with_principal XFAIL
   tests/unit/entrypoints/sse/test_handler_auth_propagation.py::TestSseAuthContextPropagation::test_execution_context_in_dispatch_call XFAIL
   tests/unit/entrypoints/sse/test_handler_auth_propagation.py::TestSseAuthContextEdgeCases::test_auth_with_no_metadata_yields_empty_permissions XFAIL
   tests/unit/entrypoints/sse/test_handler_auth_propagation.py::TestSseAuthContextEdgeCases::test_request_state_without_auth_attribute XFAIL
   ============================== 8 xfailed in 2.61s ==============================
   ```

5. **Parity-контраст**: `src/backend/entrypoints/soap/soap_handler.py:178-192`:
   ```python
   auth = getattr(request.state, "auth", None)
   context = ExecutionContext.from_auth(auth, route_id=route_id)
   exchange = await dsl.dispatch(
       route_id=route_id, body=payload,
       headers={"soap-action": ...}, context=context,
   )
   ```
   GraphQL: `src/backend/entrypoints/graphql/schema.py:442-458,541-558` — extract
   `_extract_auth_from_info(info)` → `principal, permissions` → проброс.

**Impact:**
- SSE-authenticated пользователь на protected route → fail-closed (deny), но audit/log
  показывает `"anonymous"` вместо `request.state.auth.principal`.
- SSE-authenticated пользователь на public route → execute без permission check (если
  pipeline НЕ объявляет `security=()`).
- Пароль в `principal=""` гарантирует, что `check_route_permission` на protected
  routes возвращает `allowed=False` (через `RoutePermissionDeniedError`), но **auth-events
  теряют identity**.

**Рекомендация (минимальная):**
- В `sse_invoke` добавить:
  ```python
  from src.backend.core.auth.auth_context_helpers import extract_user_permissions
  auth = getattr(request.state, "auth", None)
  principal = getattr(auth, "principal", "") or "" if auth else ""
  permissions = extract_user_permissions(auth) if auth else ()
  ```
  и пробросить в `dispatch_action_or_dsl(... principal=principal, permissions=permissions)`.

**Тест-критерий:** 8/8 тестов в `test_handler_auth_propagation.py` переходят из
`xfail` в `passed` (с `strict=True` это значит `pytest` будет fail'иться до исправления).

**Cycle-1 статус:** **RESIDUAL** — без изменений с момента cycle 1 (8 xfail тестов — тот же baseline).

---

### 4.2 DOMAIN-P0-002 — MQ Redis/RabbitMQ subscribers ACK вместо DLQ enqueue

**Evidence (read-only, точные цитаты):**

1. `src/backend/entrypoints/stream/subscribers.py:18-50` — оба handler'а:
   ```python
   @stream_client.redis_router.subscriber(
       stream=settings.redis.get_stream_name("dsl-events")
   )
   async def handle_universal_redis_action(
       body: dict, msg: RedisChannelMessage, redis: Redis
   ) -> None:
       try:
           command = ActionCommandSchema.model_validate(body)
           stream_logger.info(...)
           await action_handler_registry.dispatch(command)
       except Exception as exc:
           stream_logger.error(f"Failed to process Redis DSL action: {exc}", exc_info=True)
   ```
   → `except Exception` ловит **ВСЁ**, логирует, **возвращает нормально** → FastStream
   default `auto_ack=True` (не настроен explicit `ack=False`) → сообщение ACK'нуто и
   **удалено из очереди**. Нет `await msg.ack()`/`await msg.nack()` (значит используется
   default path, что для FastStream с broker-managed ack = `auto_ack` после return).

2. `src/backend/entrypoints/stream/invoker_subscribers.py:57-93` (MQ Invoker path):
   ```python
   async def _dispatch_invocation_message(
       body: dict[str, Any], *, correlation_id: str | None, source: str
   ) -> None:
       ...
       try:
           request = _deserialize_request(body)
       except (KeyError, ValueError, TypeError) as exc:
           stream_logger.warning(...)
           return  # ← ACK + drop (no DLQ)
       ...
       invoker = get_invoker()
       try:
           await invoker.invoke(request)
       except Exception as _:
           stream_logger.exception(...)
       # no return value → no exception → implicit ACK
   ```
   → **Аналогично**: `return` для bad-message, `except Exception` для invoker-fail,
   выход нормально → ACK. **Никакого DLQ**.

3. `src/backend/infrastructure/messaging/dlq_base.py:60-117` — DLQ-envelope + DLQWriter
   protocol **существуют**:
   ```python
   class DLQEnvelope(BaseModel):
       dlq_id: str = ...
       transport: str  # ← "mq" не существует в StrEnum
       trace_id: str | None = None
       route_id: str | None = None
       original_payload: Any = None
       error_class: str
       error_message: str
       reason: DLQReason = DLQReason.UNEXPECTED
       ...

   @runtime_checkable
   class DLQWriter(Protocol):
       async def write(self, envelope: DLQEnvelope) -> None: ...
   ```
   → Можно использовать, но **MQ-subscribers не импортируют** `DLQEnvelope`/`DLQWriter`.

4. **B-17 fix reference (cycle 37)**: `src/backend/infrastructure/clients/external/cdc/_dlq_writer_guard.py:1-14`:
   ```python
   """B-17 fix (cycle 37): DLQ-writer wiring guard для CDCClient singleton.
   ...
   до cycle 37 в production-стенде этот setter никем не вызывался —
   ``_send_to_dlq`` делал ``return`` при ``writer is None``
   и событие тихо терялось.
   """
   ```
   → **Тот же паттерн** (silent data-loss on missing writer) **воспроизведён** в
   `stream/subscribers.py` и `stream/invoker_subscribers.py`. B-17 fail-loud guard
   **не применён** к MQ-транспорту.

5. Тест подтверждает: `tests/unit/entrypoints/stream/test_subscribers.py:101-115`:
   ```python
   @pytest.mark.asyncio
   async def test_dispatch_exception(self, subscribers_fixture: Any) -> None:
       ...
       registry.dispatch = AsyncMock(side_effect=RuntimeError("dispatch err"))
       ...
       await redis_handler(body={"action": "test.b", "payload": {}}, msg=fake_msg, redis=fake_redis)
       subscribers_fixture["logger"].error.assert_called()
       # NO assertion that msg was nack'd or DLQ was written
   ```
   → Тест **фиксирует log+ack-drop** как expected behavior, **не проверяет** DLQ.

**Impact:**
- **Data loss**: poison-message (невалидный payload или dispatch-fail) теряется
  безвозвратно. Для финансовых/критических action'ов (`orders.create_skb_order` etc.) —
  **non-recoverable**. Контраст: `infrastructure/clients/external/cdc/client.py:228,247`
  делает `await self._send_to_dlq(envelope)` для тех же случаев (B-17 fix).

**Рекомендация (минимальная):**
- В `subscribers.py:21-34` и `invoker_subscribers.py:40-94` завернуть dispatch в
  `DLQEnvelope` + `await dlq_writer.write(envelope)` при exception. `dlq_writer` —
  через DI provider (как CDC client). Transport в envelope: `"redis"` / `"rabbit"`.

**Тест-критерий:** Создать `test_subscribers_dlq.py` (по аналогии с
`tests/unit/entrypoints/cdc/`): при `registry.dispatch = AsyncMock(side_effect=...)`
→ assert `dlq_writer.write` called once с envelope, содержащим
`transport=source, error_class="RuntimeError"`.

**Cycle-1 статус:** **RESIDUAL** (T-1.3 в Phase 4 plan cycle 1 — отложен).

---

### 4.3 DOMAIN-P0-003 — CDC + Filewatcher management endpoints без auth

**Evidence (read-only, точные цитаты):**

1. `src/backend/entrypoints/cdc/cdc_routes.py:38-70` (все endpoints):
   ```python
   cdc_router = APIRouter(prefix="/api/v1/cdc", tags=["CDC"])
   ...
   @cdc_router.post(
       "/subscriptions",
       response_model=CDCSubscribeResponse,
       summary="Создать CDC-подписку",
   )
   async def create_subscription(request: CDCSubscribeRequest) -> CDCSubscribeResponse:
       client = get_cdc_client_provider()
       sub_id = await client.subscribe(...)
       return CDCSubscribeResponse(...)

   @cdc_router.delete("/subscriptions/{subscription_id}", ...)
   async def delete_subscription(subscription_id: str) -> dict[str, Any]:
       client = get_cdc_client_provider()
       deleted = await client.unsubscribe(subscription_id)
       return {"deleted": deleted, "subscription_id": subscription_id}

   @cdc_router.get("/subscriptions", ...)
   async def list_subscriptions() -> list[dict[str, Any]]:
       client = get_cdc_client_provider()
       return client.list_subscriptions()
   ```
   → **НЕТ `Depends(require_auth(...))`** на router и на отдельных endpoints.

2. `src/backend/entrypoints/filewatcher/watcher_routes.py:33-69`:
   ```python
   watcher_router = APIRouter(prefix="/watchers", tags=["File Watchers"])
   ...
   @watcher_router.post("/", summary="Создать наблюдатель")
   async def create_watcher(body: CreateWatcherRequest) -> dict[str, Any]:
       spec = WatcherSpec(...)
       created = watcher_manager.add(spec)
       return {"id": created.id, ...}

   @watcher_router.delete("/{watcher_id}", ...)
   async def delete_watcher(watcher_id: str) -> dict[str, str]:
       watcher_manager.remove(watcher_id)
       return {"status": "deleted", "id": watcher_id}

   @watcher_router.get("/", ...)
   async def list_watchers() -> list[dict[str, Any]]:
       return watcher_manager.list_watchers()
   ```
   → **НЕТ auth-зависимостей**.

3. **Контраст — webhook management**: `src/backend/entrypoints/webhook/handler.py:84-127`:
   ```python
   @webhook_router.post("/subscriptions", summary="Создать подписку (auth required)")
   async def create_subscription(
       body: CreateSubscriptionRequest, auth: Any = Depends(_require_auth_dep)
   ) -> dict[str, Any]:
       ...
   ```
   → `auth: Any = Depends(_require_auth_dep)` присутствует. `(auth required)` в summary.

4. **Контраст — admin endpoints**: `src/backend/entrypoints/api/v1/endpoints/admin_cron.py`
   (проверено в 05-api.md cycle 2 phase 1) — admin-router'ы обычно подключаются через
   `setup_middlewares` + `auth_required` для `/api/v1/admin/*`. **Но CDC-router смонтирован
   на `/api/v1/cdc/`, не `/api/v1/admin/cdc/`** — поэтому admin-middleware может не
   покрывать.

5. `src/backend/entrypoints/cdc/cdc_routes.py:50-56` — `target_action` — `action`,
   который вызывается при CDC-event. Если `target_action="orders.delete"` —
   **неаутентифицированный** пользователь может:
   - Подписаться на CDC-таблицу.
   - Дождаться события (любого insert/update).
   - CDC client выполнит `target_action` (если `callback` or `target_action`).

6. `src/backend/entrypoints/filewatcher/watcher_manager.py:178-195` — file-event триггерит
   `dsl.dispatch(route_id, body={"filename": ..., "filepath": ..., "watcher_id": ...})`.
   Аналогично: неаутентифицированный пользователь создаёт watcher на `/tmp/upload` →
   `route_id="orders.create"` → `orders.create` вызывается от имени system (anonymous).

**Impact:**
- **Fail-open**: любой неаутентифицированный HTTP-клиент может:
  - Создать CDC-подписку → trigger `target_action` через CDC callback
    (см. `client.py:228-247`).
  - Удалить чужую CDC-подписку по `subscription_id` (IDOR).
  - Создать filewatcher на произвольную директорию + `route_id` → trigger DSL route.
  - Удалить чужой watcher по ID.
- Это эквивалент `DOMAIN-P0-001` fail-open, но для **management**-эндпоинтов.

**Рекомендация (минимальная):**
- В `cdc_routes.py` и `watcher_routes.py` добавить `Depends(require_auth([AuthMethod.API_KEY, AuthMethod.JWT, AuthMethod.MTLS]))` либо на router-level, либо на каждый endpoint.

**Тест-критерий:** Создать `test_cdc_routes_auth.py` + `test_watcher_routes_auth.py`:
без Authorization header → 401; с JWT → 200.

**Cycle-1 статус:** **NEW** (не упомянут в cycle 1, но логически часть T-1.2 deferred).

---

### 4.4 DOMAIN-P0-004 — MQTT handler без auth, без principal/permissions

**Evidence (read-only, точные цитаты):**

1. `src/backend/entrypoints/mqtt/mqtt_handler.py:131-157`:
   ```python
   async def _handle_message(self, topic: str, payload: bytes | bytearray) -> None:
       import orjson
       try:
           data = orjson.loads(payload)
       except Exception as _:
           data = {"raw": payload.decode("utf-8", errors="replace")}
       action = data.pop("action", None)
       if not action:
           action = self._topic_to_action(topic)
       ...
       try:
           from src.backend.dsl.commands.registry import action_handler_registry
           from src.backend.schemas.invocation import ActionCommandSchema
           command = ActionCommandSchema(
               action=action, payload=data, meta={"source": "mqtt", "topic": topic}
           )
           await action_handler_registry.dispatch(command)
   ```
   → **НЕТ** `principal` / `permissions` / `auth` в `meta`. `action_handler_registry`
   → `BaseService.method(payload)` (Tier 1/2 path, **обходит** `DslService._enforce_route_permission`).

2. **Контраст — WS auth (S172 M1.1)**: `src/backend/entrypoints/websocket/ws_handler.py:192-200`:
   ```python
   require_auth = getattr(ws_settings, "require_auth", True)
   if require_auth:
       try: await websocket.accept()
       except Exception: return
       if not await _authenticate_handshake(websocket):
           return
   ```
   → WS **обязателен** auth на handshake. MQTT — **нет**.

3. **Контраст — IMAP**: `src/backend/entrypoints/email/imap_monitor.py:115-130` —
   `password_vault_ref` + `aioimaplib.login()`. IMAP аутентифицируется на уровне
   IMAP-сервера, но `dsl.dispatch` всё равно вызывается без `context` (P1-004).
   MQTT — аналогичная проблема, но без какой-либо аутентификации в `MqttHandler`.

4. `MqttSettings` (через `src.backend.core.config.services.mqtt`): содержит
   `username`/`password` для **broker** (а не для клиента). Аутентификация MQTT-клиента
   на broker ≠ аутентификация user'а для action.

**Impact:**
- Любой клиент с credentials к MQTT-broker может publish в `gd/orders/create` →
  `action="orders.create"` → execute от имени system (no audit principal).
- Для shared-tenant сценариев — потенциальный audit-loss и RBAC-bypass.

**Рекомендация (минимальная):**
- Добавить опциональный JWT/API-key claim в MQTT-payload (например, `meta.token`),
  валидировать через `auth_selector.require_auth`. В production отказать без token
  (fail-closed).

**Тест-критерий:** Mock `aiomqtt.Client.messages` → publish payload без token →
assert `action_handler_registry.dispatch` NOT called + DLQ-write (или просто log-drop).

**Cycle-1 статус:** **NEW**.

---

### 4.5 DOMAIN-P1-001 — `subscribers.py:9` imports через `api.generator.registry`

**Evidence (read-only, точные цитаты):**

1. `src/backend/entrypoints/stream/subscribers.py:1-10`:
   ```python
   from faststream.rabbit.fastapi import RabbitMessage
   from faststream.redis.fastapi import Redis, RedisChannelMessage
   from src.backend.core.config.settings import settings
   from src.backend.core.di.providers import (
       get_stream_client_provider,
       get_stream_logger_provider,
   )
   from src.backend.entrypoints.api.generator.registry import action_handler_registry
   from src.backend.schemas.invocation import ActionCommandSchema
   ```

2. `src/backend/entrypoints/api/generator/registry.py:1-12`:
   ```python
   """Re-export action-реестра для entrypoints.
   Канонический модуль: ``app.dsl.commands.action_registry``.
   """
   from src.backend.dsl.commands.action_registry import (
       ActionHandlerRegistry, ActionHandlerSpec, action_handler_registry,
   )
   ```

3. **Канонический путь** (используется в 90% codebase): `from src.backend.dsl.commands.registry import action_handler_registry`
   — `src/backend/dsl/commands/registry.py:9-19` уже импортирует из
   `src.backend.dsl.commands.action_registry` и re-export'ит.

4. **Layer checker**: `python tools/check_layers.py --root src` → exit 0, 0 new
   (т.е. `entrypoints→entrypoints` допустимо в текущей политике). Allowlist
   содержит:
   ```
   src/backend/entrypoints/_action_bridge.py    entrypoints src.backend.dsl.service
   src/backend/entrypoints/email/imap_monitor.py entrypoints src.backend.dsl.service
   src/backend/entrypoints/filewatcher/watcher_manager.py entrypoints src.backend.dsl.service
   src/backend/entrypoints/graphql/schema.py    entrypoints src.backend.dsl.service
   ...
   ```
   Но **НЕ** содержит `stream/subscribers.py` (т.к. он импортирует `entrypoints.api.generator.registry`,
   а не напрямую `src.backend.dsl.*`). Это **anti-pattern** — entrypoint зависит от
   другого entrypoint, что нарушает инвариант "transport handlers независимы".

5. **Контраст** — в `invoker_subscribers.py:29` (тот же модуль!) используется
   `from src.backend.services.execution.invoker import ...` — корректный import
   через `services` layer.

**Impact:**
- Anti-pattern, но не critical: `api.generator.registry` — тонкий re-export,
  не содержит логики. Поведение эквивалентно `dsl.commands.registry`.
- Скрывает dependency от layer-checker'а (через цепочку entrypoint→entrypoint→dsl),
  усложняет анализ impact-graph.

**Рекомендация (минимальная):**
- Заменить `subscribers.py:9` на
  `from src.backend.dsl.commands.registry import action_handler_registry`.

**Тест-критерий:** После правки: `python tools/check_layers.py --root src` — exit 0,
allowlist не должен меняться (т.к. `entrypoints→dsl.commands.registry` уже allowed).

**Cycle-1 статус:** **RESIDUAL** — `subscribers.py` не изменился между cycle 1 и
cycle 2 (фиксация через cycle 1 не делалась).

---

### 4.6 DOMAIN-P1-002 — WS / Webhook / Express не передают principal в bridge

**Evidence (read-only, точные цитаты):**

1. `src/backend/entrypoints/websocket/ws_handler.py:286-295`:
   ```python
   bridge = await dispatch_action_or_dsl(
       action_id=action,
       dsl_route_id=action,
       payload=data.get("payload", {}),
       transport="ws",
       headers={"ws-client-id": client_id, "ws-action": action},
       attributes={"client_id": client_id},
   )
   ```
   → `websocket.state.ws_session.principal` (set on line 152) **НЕ передаётся**.

2. `src/backend/entrypoints/webhook/handler.py:183-194`:
   ```python
   bridge = await dispatch_action_or_dsl(
       action_id=f"webhook.{event_type}",
       dsl_route_id=f"webhook.{event_type}",
       payload=payload,
       transport="webhook",
       headers={"x-source": "webhook", "x-webhook-event": event_type, ...},
       attributes={"event_type": event_type, "client_ip": client_ip},
   )
   ```
   → Webhook не имеет user-identity (per-design — это system-inbound). `principal=""` + `permissions=()`
   **допустимо**, но **должно быть явно задокументировано** (сейчас — default).

3. `src/backend/entrypoints/express/router.py:198-206, 209-217`:
   ```python
   bridge = await dispatch_action_or_dsl(
       action_id=route_id, dsl_route_id=route_id, payload=payload,
       transport="express",
       headers={..., "X-Express-User-Huid": (payload.get("from") or {}).get("user_huid", "")},
       correlation_id=sync_id or None,
       attributes={"sync_id": sync_id} if sync_id else None,
   )
   ```
   → `user_huid` кладётся в `headers` (теряется для permission check), но **НЕ передаётся
   в `principal=`**. После DOMAIN-P0-001 — должно быть исправлено.

**Impact:** Парность с DOMAIN-P0-001. Protected routes → fail-closed (anonymous → deny).
Public routes → execute без permission check.

**Рекомендация:** После fix DOMAIN-P0-001 (SSE) — патч повторить для ws_handler,
express (3 endpoint'а), webhook (если считать `principal="webhook:anonymous"` явно
declared).

**Тест-критерий:** Forward-looking TDD — добавить `test_ws_handler_auth_propagation.py`
по аналогии с SSE (8 xfail → 0 xfail).

**Cycle-1 статус:** **NEW** (не было P1 в cycle 1; DOMAIN-P0-001 — только SSE).

---

### 4.7 DOMAIN-P1-003 — MCP `route_execute` tool bypass permission

**Evidence (read-only, точные цитаты):**

1. `src/backend/entrypoints/mcp/mcp_server/tools_route.py:55-95`:
   ```python
   @mcp.tool(
       name="route_execute",
       description="Выполняет DSL-маршрут по route_id с указанным payload...",
   )
   async def route_execute(route_id: str, payload: str = "{}") -> str:
       from src.backend.dsl.engine.execution_engine import ExecutionEngine
       from src.backend.dsl.registry import route_registry
       try:
           pipeline = route_registry.get(route_id)
       except KeyError:
           return encode_json({"error": f"Route '{route_id}' not found"}).decode("utf-8")
       try:
           parsed = orjson.loads(payload) if payload else {}
       except (orjson.JSONDecodeJSONDecodeError, TypeError):
           parsed = {"raw": payload}
       engine = ExecutionEngine()
       exchange = await engine.execute(pipeline, body=parsed)  # ← NO context!
       ...
   ```
   → `engine.execute(pipeline, body=parsed)` **без `context=`** → `ExecutionContext()`
   default → `principal=""` → **anonymous** в `_enforce_route_permission`.

2. **Design-документация** в `tests/unit/entrypoints/mcp/test_mcp_no_dsl_principal_propagation.py:24-37`:
   ```
   DSL-fallback (Tier 3) — не применим к MCP: MCP tools зарегистрированы
   через ``@mcp.tool(...)``, не через ``route_registry``. DSL-routes
   недоступны как MCP tools в текущей архитектуре.
   ```
   → Test утверждает, что DSL-routes **не доступны** как MCP tools. **Но `route_execute`
   ЯВЛЯЕТСЯ MCP tool**, который **напрямую** вызывает `engine.execute`.

3. **Auth на ASGI**: `src/backend/entrypoints/mcp/auth_middleware.py` (McpAuthMiddleware)
   блокирует anon → 401 (`tests/unit/entrypoints/mcp/test_mcp_no_dsl_principal_propagation.py:179-220`).
   → ASGI-аутентификация есть, **но principal/permissions НЕ пробрасываются** в
   `ExecutionContext` внутри `route_execute`.

4. **Test failure подтверждает**:
   ```
   tests/unit/entrypoints/mcp/test_mcp_no_dsl_principal_propagation.py::TestMcpAuthBypassDesign::test_authz_manual_tool_does_not_invoke_dispatch_dsl FAILED
       AttributeError: module 'src.backend.entrypoints.mcp.mcp_server.helpers' has no attribute '_authz_manual_tool'
   tests/unit/entrypoints/mcp/test_mcp_no_dsl_principal_propagation.py::TestMcpToolAuthzBypass::test_disallowed_tool_returns_deny_envelope FAILED
       AttributeError: module 'src.backend.entrypoints.mcp.mcp_server.helpers' has no attribute '_authz_manual_tool'
   ```
   → 2/4 теста в этом файле **FAILED** (тесты forward-looking, ссылаются на
   несуществующие `_authz_manual_tool` и `_check_mcp_manual_tool_authz`).

**Impact:**
- MCP `route_execute` — anonymous execute of any DSL route, bypassing RBAC.
- Это менее критично, чем SSE, потому что MCP уже проходит ASGI-auth, но
  **parity с L5 Security Chain** нарушена.

**Рекомендация (минимальная):**
- В `tools_route.py:55-95` добавить `context=ExecutionContext.from_auth(auth, route_id=route_id)`
  и пробросить в `engine.execute(pipeline, body=parsed, context=context)`.
- Auth извлекать из `mcp.request_context` (FastMCP API).

**Тест-критерий:** `route_execute` без `auth` на protected route → BridgeResult fail-closed.

**Cycle-1 статус:** **NEW**.

---

### 4.8 DOMAIN-P1-004 — IMAP + Filewatcher dispatch без context

**Evidence (read-only, точные цитаты):**

1. `src/backend/entrypoints/email/imap_monitor.py:253-263`:
   ```python
   try:
       dsl = get_dsl_service()
       await dsl.dispatch(
           route_id=self.config.route_id,
           body=msg_data,
           headers={"x-source": "email_imap", "x-email-from": msg_data.get("from", ""), ...},
           # ← NO context= kwarg
       )
   ```
   → `dsl.dispatch` без `context=` → `ExecutionContext()` default → `principal=""`.

2. `src/backend/entrypoints/filewatcher/watcher_manager.py:184-193`:
   ```python
   try:
       dsl = get_dsl_service()
       await dsl.dispatch(
           route_id=spec.route_id,
           body={"filename": ..., "filepath": ..., "watcher_id": watcher_id},
           headers={"x-source": "filewatcher", "x-watcher-id": watcher_id},
           # ← NO context= kwarg
       )
   ```
   → **Аналогично**.

**Impact:**
- System-events (IMAP email, FS change) триггерят DSL-routes от имени "anonymous".
  На protected routes — fail-closed. На public routes — execute без check.
- Audit/логи теряют user-identity (т.к. его нет) — это **by-design** для system-events.
  Но требует явного `principal="system:imap"` / `"system:filewatcher"` для observability.

**Рекомендация (минимальная):**
- Создать `principal=f"system:{source}"` (e.g. `"system:imap"`, `"system:filewatcher"`)
  и `permissions=("system:dispatch",)` явно, чтобы audit-trail показывал system-origin.

**Тест-критерий:** `test_imap_monitor.py` + `test_watcher_manager.py` — assert
`context.principal.startswith("system:")`.

**Cycle-1 статус:** **NEW** (по паттерну аналогично P0-001, но менее критично).

---

### 4.9 DOMAIN-P2-001 — `BaseEntrypoint` (dead code per docstring)

**Evidence (read-only, точные цитаты):**

1. `src/backend/entrypoints/base.py:90-145` — `BaseEntrypoint` class:
   ```python
   class BaseEntrypoint(ABC):
       """Абстрактный базовый класс для всех entrypoints (S171 M10 P2, D176).
       ...
       .. deprecated:: S171 M10
           BaseEntrypoint определён, но НЕ наследуется ни одним протоколом.
           Реальная унификация идёт через свободную функцию ``dispatch_action()``.
           Класс сохранён для backward-compat (внешние интеграции могут импортировать).
           Новые протоколы должны использовать ``dispatch_action()`` напрямую.
       """
   ```

2. **Использование в `src/backend/entrypoints/`**: только `base.py:35` (`__all__`),
   ни одного `from entrypoints.base import BaseEntrypoint` или
   `class ...(BaseEntrypoint)` внутри scope.

3. **Test-only usage**: `tests/unit/entrypoints/test_base.py:62`:
   ```python
   class DummyEntrypoint(BaseEntrypoint):
       protocol = "dummy"
       async def handle(self, *args: Any, **kwargs: Any) -> Any:
           return "handled"
   ```
   → Только в test. Никаких production-usages.

4. Также `tests/unit/tools/test_check_layers_lazy_imports.py:278` — упоминает
   `BaseEntrypoint` как имя в lazy-import allowlist (не использование).

**Impact:**
- ~50 LOC мёртвого кода (class definition + abstract method).
- Удаление сломает `test_base.py::test_base_entrypoint_dispatch` и
  `test_base_entrypoint_serialize_result/format_error` (3 теста).

**Рекомендация (минимальная):**
- Оставить `dispatch_action` (используется повсеместно). Удалить `BaseEntrypoint` class.
- Удалить 3 теста в `test_base.py:69-89`.

**Тест-критерий:** После удаления — `pytest tests/unit/entrypoints/test_base.py` → 4 passed (только `dispatch_action` тесты).

**Cycle-1 статус:** **NEW**.

---

### 4.10 DOMAIN-P2-002 — `event_bus` singleton + CDC/filewatcher без tenant propagation

**Evidence (read-only, точные цитаты):**

1. `src/backend/entrypoints/sse/handler.py:51-96` — `EventBus` class:
   ```python
   class EventBus:
       def __init__(self) -> None:
           self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []
       ...
   event_bus = EventBus()  # module-level singleton
   ```
   → In-memory `asyncio.Queue` per-process. На multi-worker deployment
   (`uvicorn --workers 4`) — события из worker-1 не видны подписчикам в worker-2.

2. `src/backend/entrypoints/cdc/cdc_routes.py:38-70` — нет `Depends(tenant_dep)`.
   `get_cdc_client_provider()` → `client.subscribe(...)` → callback с no tenant-info.

3. **Контраст — другие entrypoints** (проверено в 05-api.md cycle 2): REST API
   использует `Depends(tenant_dep)` для per-tenant routing.

**Impact:**
- SSE event_bus — **architectural limitation**, не dead code. Горизонтальное
  масштабирование ломает pub/sub.
- CDC/Filewatcher routes — отсутствие tenant-id ухудшает per-tenant quotas и
  audit-trail.

**Рекомендация (минимальная):**
- `event_bus` — заменить на Redis pub/sub (EIP-style `publish-subscribeChannel`).
  Уже установлено: `redis>=5.0` (uv.lock).
- CDC routes — добавить `Depends(tenant_dep)`.

**Тест-критерий:** После fix — `test_event_bus.py` интеграционный с реальным Redis.

**Cycle-1 статус:** **NEW**.

---

### 4.11 DOMAIN-P3-001 — Deprecated `faststream.*.fastapi` imports

**Evidence (read-only, точные цитаты):**

1. `src/backend/entrypoints/stream/subscribers.py:1-2`:
   ```python
   from faststream.rabbit.fastapi import RabbitMessage
   from faststream.redis.fastapi import Redis, RedisChannelMessage
   ```

2. `src/backend/entrypoints/stream/invoker_subscribers.py:22-23`:
   ```python
   from faststream.rabbit.fastapi import RabbitMessage
   from faststream.redis.fastapi import Redis, RedisChannelMessage
   ```

3. `src/backend/infrastructure/clients/messaging/stream.py:126,149,183`:
   ```python
   from faststream.redis.fastapi import RedisRouter  # line 126
   from faststream.rabbit.fastapi import RabbitRouter  # line 149
   from faststream.kafka.fastapi import KafkaRouter    # line 183
   ```

4. **Test output** (`tests/unit/entrypoints/stream/test_subscribers.py`):
   ```
   DeprecationWarning: The integration has been moved to the faststream_fastapi package
   and will be removed in 1.0.0 version.
   `pip install faststream_fastapi`
   https://github.com/faststream-community/faststream_fastapi
   ```

5. **pyproject.toml**: `faststream[kafka]>=0.6.7,<1.0.0` присутствует;
  `faststream_fastapi` **отсутствует**.

**Library replacement:**
- Библиотека: `faststream_fastapi` (community-package, рекомендация upstream).
- License: Apache-2.0 (как у `faststream`).
- Maintenance: `faststream-community/faststream_fastapi` — community-maintained,
  non-Apache org. Риск: medium (low bus-factor, но upstream faststream рекомендует).

**LOC delta:** 0 (drop-in: `from faststream_fastapi.RabbitMessage import ...` или
аналогичный re-export). Возможно +1 LOC в `pyproject.toml`.

**Cycle-1 статус:** **NEW**.

---

### 4.12 DOMAIN-P3-002 — Custom retry/reconnect без `tenacity`

**Evidence (read-only, точные цитаты):**

1. `src/backend/entrypoints/stream/invoker_subscribers.py:60-66` (docstring):
   ```
   Ошибки парсинга → лог + drop (consumer не должен retry'ить bad message).
   Ошибки Invoker → уже залогированы внутри; consumer ack'ает сообщение
   в любом случае, чтобы избежать infinite redelivery — повторная попытка
   через :class:`InvocationStatus.ERROR` в reply-канале.
   ```
   → **infinite loop risk** на poison-message: `asyncio.sleep(5)` reconnect, но
   **нет max-retry** на dispatch.

2. `src/backend/entrypoints/mqtt/mqtt_handler.py:128-129`:
   ```python
   except Exception as exc:
       logger.error("MQTT connection error: %s. Reconnecting in 5s...", exc)
       await asyncio.sleep(5)
   ```
   → Hard-coded `sleep(5)`, no exponential-backoff, no max-retry.

3. `src/backend/entrypoints/mqtt/mqtt_handler.py:131-157` (`_handle_message`):
   no retry на dispatch error, only `logger.error`.

4. **Already-installed**: `tenacity` (проверено — есть в `pyproject.toml`).

**Library replacement:**
- Библиотека: `tenacity` (Apache-2.0, mature, v8+).
- License: Apache-2.0.
- Maintenance: active.

**LOC delta:** -10..-20 (заменяет hardcoded `sleep(5)` на `tenacity.Retrying`).

**Cycle-1 статус:** **NEW**.

---

## 5. Cycle-1 residuals (verified или mutated)

| Cycle-1 ID | Cycle-1 title | Cycle-2 status | Evidence |
|---|---|---|---|
| **DOMAIN-P0-001** | SSE `/events/invoke` principal/permissions в DslService.dispatch | **RESIDUAL** | 8/8 `xfail strict=True` тестов в `test_handler_auth_propagation.py:50-377` — проброс `principal`/`permissions` НЕ реализован. См. §4.1. |
| **DOMAIN-P0-002** | MQ Redis/RabbitMQ entrypoints ack вместо DLQ enqueue | **RESIDUAL** | `subscribers.py:21-34, 38-50` и `invoker_subscribers.py:40-94` по-прежнему `except Exception → log → implicit ACK`. См. §4.2. |
| **P1-001** | `entrypoints/stream/subscribers.py:9` layer violation | **RESIDUAL** (но не критично) | `from src.backend.entrypoints.api.generator.registry import action_handler_registry` — всё ещё присутствует в cycle 2. Layer checker exit 0, но это **anti-pattern** (entrypoint→entrypoint). См. §4.5. |
| **T-1.2 (deferred from cycle 1 Phase 4)** | SSE/HITL auth | **RESIDUAL** | См. DOMAIN-P0-001. |
| **T-1.3 (deferred from cycle 1 Phase 4)** | MQ DLQ data-loss | **RESIDUAL** | См. DOMAIN-P0-002. |
| **T-1.1 (deferred from cycle 1 Phase 4)** | composition root | **NOT IN SCOPE** | Этот отчёт — entrypoints domain; composition root — отдельный домен. Не атрибутируется. |

**Иные cycle-1 finding-IDs, упомянутые в cycle-1 markdown:**
- Cycle-1 не привёл полный список для entrypoints-domain. Сканированы: cycle 1
  phase-4 files → `T-1.4`, `T-1.5`, `T-3.1` — это source-правки, **не в scope** этого
  аудита. `M` flags в `git status` → не cycle 2 атрибуция.
- Cycle 1 finding P0/Sprint 1.1 "route-wide permission enforcement" — **MUTATED**:
  реализован в `src/backend/dsl/service/facade.py:62-90` (`_enforce_route_permission`)
  + `src/backend/dsl/engine/context.py:39-77` (`ExecutionContext.from_auth`). Работает
  для **SOAP** + **GraphQL** (parity-pattern применён). **Не работает** для SSE, WS,
  Webhook, Express, MQTT, IMAP, Filewatcher — см. DOMAIN-P0-001/004, P1-002/004.
- Cycle 1 finding P0/Sprint 1.4 "L5 Security Chain migration" — **MUTATED**:
  forward-looking TDD scaffolded (`test_handler_auth_propagation.py:50-57`,
  `test_mcp_no_dsl_principal_propagation.py:39-43`), но **миграция не завершена**.
  8/8 SSE тестов `xfail`, 2/4 MCP тестов `FAILED` (API mismatch на
  `_authz_manual_tool`).

---

## 6. Contradictions / overlaps to flag

1. **B-17 fix pattern (cycle 37) НЕ применён к MQ subscribers**: CDC client
   (`infrastructure/clients/external/cdc/client.py:267-274`) имеет fail-loud
   `_send_to_dlq` + `_dlq_required` + `DLQWriterGuard`. MQ subscribers
   (`entrypoints/stream/subscribers.py`, `invoker_subscribers.py`) — **тот же
   data-loss pattern** воспроизведён **без** guard'а. **Overlap с DOMAIN-P0-002**.

2. **`@deprecated BaseEntrypoint` ↔ `dispatch_action` co-existence**: `base.py:90-103`
   явно говорит, что `BaseEntrypoint` не используется. Но он остаётся
   (для backward-compat). `dispatch_action` — primary API. **Anti-pattern +
   dead-code overlap** (DOMAIN-P2-001).

3. **CDC routes ↔ CDC client (B-17 fix)**: CDC client имеет fail-loud DLQ guard
   (S176 cycle 33 + B-17 cycle 37). **Но CDC routes не защищены auth** (DOMAIN-P0-003)
   — неаутентифицированный клиент может создать подписку, которая потом триггерит
   `_dispatch_change` → `_send_to_dlq` → spam DLQ.

4. **SSE handler использует `event_bus` singleton (DOMAIN-P2-002)** — in-memory
   per-process. На multi-worker deployment события не пересекают процессы. **EIP-pattern
   violation** (`publish-subscribeChannel` должен быть broker-mediated).

5. **Test `test_mcp_no_dsl_principal_propagation.py` FAILED на
   `helpers._authz_manual_tool`**: тест forward-looking, ссылается на API, который
   не существует в helpers.py. **Test-code drift** — тесты не синхронизированы с
   production-code. Не критично (xfail, не блокер), но указывает на неполную migration
   (Sprint 1.4 L5).

6. **`@mcp.tool("route_execute")` direct `engine.execute()`** (DOMAIN-P1-003) —
   противоречит by-design утверждению в `test_mcp_no_dsl_principal_propagation.py:24-37`,
   что "DSL-routes не доступны как MCP tools". **Documentation/code drift**.

7. **3 entrypoint-callsite'а передают headers, но не principal** (DOMAIN-P1-002):
   `X-Express-User-Huid` в `headers` — это **header-level propagation**, не
   `principal` для permission check. Header может быть подделан клиентом; principal —
   из `request.state.auth` (server-trusted). **Fail-open pattern, partial-mitigation
   false sense of security.**

8. **Cycle-1 ↔ cycle-2 протокол**: cycle 1 baseline сказал "175 legacy" — cycle 2
   подтверждает **175 legacy / 0 new** (не 180). Пользовательская формулировка
   "173→180" — **misinterpretation** (180 = line-count allowlist файла, не violations).

---

## 7. Readiness score 0–100

**Формула:**
```
score = 100
  - 15 * count(P0)     # P0: security/data-loss/fail-open
  -  7 * count(P1)     # P1: layer boundaries / principal-propagation
  -  3 * count(P2)     # P2: dead code
  -  1 * count(P3)     # P3: library replacement (info only)
  -  0 * count(P4)     # P4: new feature
  -  cap(score, 0)
```

**Расчёт (для текущего аудита):**
```
P0 = 4  (DOMAIN-P0-001 SSE, -002 MQ, -003 CDC/filewatcher auth, -004 MQTT auth)
P1 = 4  (P1-001 stream subscribers, -002 ws/webhook/express, -003 MCP route_execute,
          -004 IMAP/filewatcher)
P2 = 2  (P2-001 BaseEntrypoint dead, -002 event_bus singleton + tenant propagation)
P3 = 2  (P3-001 faststream_fastapi, -002 tenacity)
P4 = 0

score = 100 - 15*4 - 7*4 - 3*2 - 1*2 - 0*0
      = 100 - 60 - 28 - 6 - 2
      = 4
```

**Constraint:** `score >= 80` ЗАПРЕЩЕНО при наличии P0/P1 → **score должен быть <= 79**
если есть P0/P1. У нас 4 P0 + 4 P1 → **score = 4** (cap at 0 if negative).

**Обоснование:**
- 4 P0 security/data-loss/race/fail-open — блокеры для production.
- 4 P1 layer/principal-propagation — нарушают fail-closed invariant.
- 2 P2 dead-code/architectural — накопление tech-debt.
- 2 P3 — info-only, не блокеры, но deprecated API в новом коде.

**Readiness: 4 / 100** (PRODUCTION-NOT-READY)

**Подробный обзор по приоритетам:**

| Priority | Count | Blocker | Score impact |
|---|---|---|---|
| P0 (security/data-loss/fail-open) | 4 | YES | -60 |
| P1 (layer boundaries/principal) | 4 | YES | -28 |
| P2 (dead code) | 2 | No (cleanup) | -6 |
| P3 (library replacement) | 2 | No (info) | -2 |
| P4 (new feature) | 0 | No | 0 |

---

## 8. Recommended next tasks

1. **(P0, Blocker, MUST)** — Исправить DOMAIN-P0-001: пробросить `principal`/`permissions`
   из `request.state.auth` в `dispatch_action_or_dsl` внутри `sse_invoke`. 8/8 xfail
   тестов должны перейти в pass. **Effort:** S (~1-2 hours).

2. **(P0, Blocker, MUST)** — Исправить DOMAIN-P0-002: добавить DLQ-enqueue через
   `DLQWriter` в MQ subscribers (`subscribers.py`, `invoker_subscribers.py`).
   Применить B-17 fail-loud pattern (как в CDC). **Effort:** M (~3-5 hours).

3. **(P0, Blocker, MUST)** — Исправить DOMAIN-P0-003: добавить
   `Depends(require_auth(...))` на CDC routes + Filewatcher routes. **Effort:** S.

4. **(P0, Blocker, MUST)** — Исправить DOMAIN-P0-004: добавить JWT/API-key claim
   validation в MQTT `_handle_message`. **Effort:** M (нужен protocol-design для
   MQTT-claims).

5. **(P1, MUST)** — Применить parity-pattern из SSE/WS/Webhook/Express/IMAP/Filewatcher:
   `ExecutionContext.from_auth(auth, route_id=...)` для всех DSL-dispatch sites.
   **Effort:** M.

6. **(P1, SHOULD)** — Исправить MCP `route_execute` tool: extract principal/permissions
   из FastMCP request_context, пробрасывать в `engine.execute(context=...)`. **Effort:** S.

7. **(P2, COULD)** — Удалить `BaseEntrypoint` class из `entrypoints/base.py:90-145`
   + 3 теста в `test_base.py:69-89`. **Effort:** XS.

8. **(P2, COULD)** — Заменить in-memory `event_bus` на Redis pub/sub. **Effort:** L.

9. **(P3, OPTIONAL)** — Мигрировать `faststream.*.fastapi` → `faststream_fastapi` package.
   **Effort:** S.

10. **(P3, OPTIONAL)** — Применить `tenacity` для MQ reconnect (заменить hardcoded
    `asyncio.sleep(5)`). **Effort:** S.

11. **(cycle 2 Phase 2 prep)** — Задокументировать **resolved** cycle-1 deferred:
    T-1.2 (SSE/HITL auth — blocked by DOMAIN-P0-001 fix), T-1.3 (MQ DLQ — blocked by
    DOMAIN-P0-002 fix).

12. **(cycle 2 Phase 3 prep)** — Расследовать несоответствие user-reported "173→180"
    vs actual "175 stable". Возможно, в чьём-то tooling'е line-count allowlist
    интерпретируется как violations count.

---

## 9. Commands run (verified, read-only)

```bash
# Layer checker — confirm baseline 175/0
$ timeout 180 python tools/check_layers.py --root src
Нарушений: 0 новых  (файлов: 2273; baseline: 175 legacy)
exit 0

# Allowlist line count
$ wc -l tools/check_layers_allowlist.txt
180 tools/check_layers_allowlist.txt
# 5 comment + 175 entry = 180 lines

# Entrypoints in allowlist
$ grep -E "^src/backend/entrypoints/" tools/check_layers_allowlist.txt | wc -l
59
# 59 entrypoint entries в allowlist (legacy)

# Security allowlist (cycle 2 baseline)
$ grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt
35

# SSE auth propagation tests (DOMAIN-P0-001 evidence)
$ .venv/bin/python -m pytest tests/unit/entrypoints/sse/test_handler_auth_propagation.py -v
collected 8 items
... 8 xfailed in 2.61s
# 8/8 XFAIL — confirms DOMAIN-P0-001 is RESIDUAL

# Stream subscribers + MCP no-dsl principal tests
$ timeout 180 .venv/bin/python -m pytest \
    tests/unit/entrypoints/sse/test_handler_auth_propagation.py \
    tests/unit/entrypoints/mcp/test_mcp_no_dsl_principal_propagation.py \
    tests/unit/entrypoints/stream/test_subscribers.py \
    -v --tb=short
# 8 xfailed (SSE), 2 failed (MCP — _authz_manual_tool not found), 6 passed (stream)

# Base entrypoint tests
$ timeout 60 .venv/bin/python -m pytest tests/unit/entrypoints/test_base.py -x --no-header
7 passed in 0.32s

# FastStream deprecation warnings
$ .venv/bin/python -m pytest tests/unit/entrypoints/stream/test_subscribers.py --no-header
... 2 warnings in 2.24s
# DeprecationWarning: The integration has been moved to the faststream_fastapi package
# and will be removed in 1.0.0 version.
```

---

## 10. Verification gates

| Gate | Expected | Actual | Status |
|---|---|---|---|
| `python tools/check_layers.py --root src` | exit 0, 175 legacy | exit 0, 175 legacy | ✅ |
| `grep -cE "^CVE-\|^GHSA-\|^PYSEC-" .security/pip-audit-allowlist.txt` | 35 | 35 | ✅ |
| `wc -l tools/check_layers_allowlist.txt` | 180 (5 comment + 175 entry) | 180 | ✅ |
| `make check-docstrings MAX_ALLOWED=0` (cycle 2 baseline) | exit 0 | not run (per scope: entrypoints domain only) | — |
| Pre-existing `M uv.lock` etc. не тронуты | да | git status показывает `M uv.lock` (не модифицировался) | ✅ |
| Pre-existing 5 uncommitted source правок cycle 1 Phase 4 не атрибутированы | да | все 5 упомянуты в §1.2 как "out of scope" | ✅ |

---

## 11. Final notes

- **Score: 4/100** (PRODUCTION-NOT-READY, 4 P0 + 4 P1 blockers).
- **P0 blockers** (4): DOMAIN-P0-001 SSE principal, DOMAIN-P0-002 MQ DLQ,
  DOMAIN-P0-003 CDC/Filewatcher auth, DOMAIN-P0-004 MQTT auth.
- **Layer violations**: **НЕ растут** (175 = 175). User-reported "173→180"
  = misinterpretation of allowlist line-count.
- **B-17 fail-loud pattern** существует в CDC client, но **не применён** к новому
  MQ-транспорту (DOMAIN-P0-002).
- **Test drift**: `test_mcp_no_dsl_principal_propagation.py` ссылается на
  несуществующее `_authz_manual_tool` (forward-looking TDD, 2/4 FAILED).
- **Tests passing**: 7/7 в `test_base.py`, 6/6 в `test_subscribers.py`, 8/8 XFAIL в
  `test_handler_auth_propagation.py` (по дизайну).
- **Coverage gap**: gRPC servicer-flow, MCP helpers, WebSocket broadcast,
  email/__init__.py, http3 internals — **не проверено** в этой фазе (см. §1.2).
- **Pre-existing drift не атрибутируется** рою cycle 2 (5 uncommitted cycle-1
  правок, `M uv.lock` -15 svcs, `M tools/blue_green.sh`, `M test_blue_green_switch.py`,
  `?? pip-audit.json`, `?? .blue_green.state`).
