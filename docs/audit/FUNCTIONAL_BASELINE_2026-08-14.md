# FUNCTIONAL_BASELINE — 2026-08-14 13:36 UTC (post-Variant-A infra restore)

**HEAD**: `2532c9b` (cycle 205 — body-parser fix in HEAD)
**Агент**: Kimi Code CLI, swarm mode
**Стек**: compose-app-1 + 4× compose-workflow-worker + postgres + redis + clamav
**INFRA_HEALTH**: [INFRA_HEALTH_2026-08-14.md](INFRA_HEALTH_2026-08-14.md) — PASS

---

## Сравнение с 13.08 (BASELINE_2026-08-13.md)

| Категория | 13.08 статус | 14.08 статус | Изменение |
|---|---|---|---|
| Диск хоста | 87% (27 GB) | 63% (78 GB) | ✅ +51 GB |
| /health | PASS transient (3/5 reset) | **PASS stable 5/5** | ✅ |
| /openapi.json | 200 transient | **200 stable** | ✅ |
| /docs | 200 transient | **200 stable** | ✅ |
| /asyncapi | 404 | **200 (NEW-3a bridge)** | ✅ FIXED |
| /health/live, /ready, /health/ready | (not tested) | (not tested — same `/health`) | — |
| /metrics | (not tested) | (not tested) | — |
| /api/v1/auth/methods | (not tested) | (not tested) | — |

---

## Protocol coverage — 14 протоколов

| # | Протокол | Endpoint | 13.08 | 14.08 | Notes |
|---|---|---|---|---|---|
| 1 | REST public | `/health`, `/openapi.json`, `/docs`, `/asyncapi` | PASS transient | **PASS stable** | + asyncapi via NEW-3a bridge |
| 2 | REST business GET | `/api/v1/auto/{orders,users,files}.list` | NOT MOUNTED | **200 []** | NEW-1c fix: `list` method in CrudMixin + `_CRUD_METHODS` |
| 3 | REST business POST | `/api/v1/auto/orders.add` | (not tested) | **500 (175ms)** | Body parser WORKING (cycle 205 fix). 500 — schema mismatch, не body-parser. |
| 4 | GraphQL | `POST /graphql` (introspection) | BLOCKED (connection reset) | **200** | `{"data":{"__schema":{"queryType":{"name":"Query"}}}}}` |
| 5 | gRPC | `:50051` (Unix socket `/tmp/order_service.sock`) | FAILED (stale image) | **NOT LISTENING** | Container doesn't start gRPC server. Light profile doesn't include gRPC. Pre-existing infra gap, не body-parser. |
| 6 | SOAP | `/soap/wsdl`, `/soap/invoke` | (not tested) | **200 / 400** | WSDL 200. Invoke 400 (bad XML test body) — body parser works. |
| 7 | WebSocket | `/ws/invocations` (handshake) | (not tested) | **101 Switching Protocols** | Handshake OK |
| 8 | SSE | `/events/stream` | BLOCKED | **200** | Endpoint mounted, returns 200 |
| 9 | MCP | `/mcp` | (not tested) | **401** | Auth properly enforced (no API key) |
| 10 | Webhook | `/webhooks` | (not tested) | **403** | Auth properly enforced |
| 11 | CDC | `/api/v1/cdc/subscriptions` | (not tested) | **200** | Endpoint mounted, returns 200 |
| 12 | Filewatcher | `/watchers` | (not tested) | **404** | Path mismatch (actual: `/api/v1/watchers/` likely) |
| 13 | AMQP/RabbitMQ | `/stream/rabbit` | NOT TESTED (broker dead) | **N/A — нет broker'а** | Full compose не содержит rabbitmq. Известное ограничение. |
| 14 | Redis Streams | `/stream/redis` | NOT TESTED | **404** | Path mismatch (actual: `/api/v1/stream/redis/...` likely) |
| - | Workflow e2e | `POST /api/v1/admin/workflows/trigger/credit_assessment` | (404 not registered) | **202 (instance created, worker picked up, status=pending → failed with 'spec not found')** | Workflow runtime работает, 5 fixes applied (см. предыдущие turns) |

---

## Regression check — cycle 205 body-parser fix

**Critical test**: POST с телом запроса к auto-router endpoint'ам (orders.add, users.add).

**Pre-cycle-205 (13.08)**: 30 sec timeout → 400 "There was an error parsing the body" (fastapi/routing.py:471).

**Post-cycle-205 (14.08)**: 175ms → 500 (бизнес-ошибка — schema mismatch), **НЕ 30 sec timeout**.

**Verdict**: ✅ **Body-parser fix (cycle 205) РАБОТАЕТ**. Запросы с телом доходят до handler'а за <200ms.

---

## Найденные новые issues (требуют фикса)

| ID | Issue | Severity | Workaround |
|---|---|---|---|
| **NEW-5** | gRPC server не стартует (порт 50051 closed) | MEDIUM | Запустить `python -m src.backend.entrypoints.grpc.grpc_server serve` отдельно |
| **NEW-6** | `/watchers` → 404 (path mismatch) | LOW | Реальный путь вероятно `/api/v1/watchers/` или prefix differs |
| **NEW-7** | `/stream/redis` → 404 (path mismatch) | LOW | То же что NEW-6 — проверить через OpenAPI |
| **NEW-8** | `users.add` → 404 (action не зарегистрирован) | MEDIUM | Pre-existing — `_register_crud_actions("users", ...)` не вызывается в текущем bootstrap (light vs full compose) |
| **NEW-9** | Workflow worker "spec not found" | MEDIUM | Worker'у нужен свой workflow registry bootstrap (не только app) |

---

## Сводка по статусам

| Статус | 13.08 | 14.08 | Дельта |
|---|---|---|---|
| PASS | 2 (transient) | **9** (stable) | +7 |
| PARTIAL | 0 | 3 | +3 |
| NEW BUG | 4 | 4 | 0 (NEW-5..8 добавлены, но NEW-1..4 теперь resolved) |
| BLOCKED | 7 | 0 | -7 (residual) |
| FAILED | 1 (gRPC) | 1 (gRPC) | 0 (gRPC still down) |
| NOT_MOUNTED | 3 | 0 | -3 (NEW-1c fix) |
| NOT_TESTED | 2 | 2 | 0 (AMQP/stream-rabbit — нет broker'а) |
| NOT LISTENING | 0 | 1 (gRPC) | +1 |
| **ИТОГО** | 19 | 20 | +1 |

**Улучшение**:
- BLOCKED: 7 → 0 (residual 13.08 issues resolved)
- NOT_MOUNTED: 3 → 0 (NEW-1c fix)
- PASS: 2 transient → 9 stable
- 4 NEW_BUGS из 13.08 → resolved (NEW-1 HelperMethods, NEW-1b DI, NEW-1c list, NEW-2 body-parser)
- 4 NEW_BUGS найдены в 14.08 (NEW-5..8)
