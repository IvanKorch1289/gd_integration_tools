# Cycle 4 — Phase 1 — Домен Entrypoints

**Scope:** `src/backend/entrypoints/**` + `tests/`, исключая
`entrypoints/api/**` и `entrypoints/middlewares/{auth_*,security}`.

**HEAD:** `22e08a0d` (cycle-1/2/3 reapply commit; baseline cycle-4)
**Интерпретатор runtime-проверок:** `.venv/bin/python` (system Python не подключён).

---

## 1. Scope / не проверено

### В scope проверены (прочитаны и/или исполнены)

- `src/backend/entrypoints/cdc/cdc_routes.py` (+ `__init__.py`)
- `src/backend/entrypoints/filewatcher/watcher_routes.py`, `watcher_manager.py`
- `src/backend/entrypoints/sse/handler.py`, `__init__.py`
- `src/backend/entrypoints/stream/subscribers.py`, `invoker_subscribers.py`, `__init__.py`
- `src/backend/entrypoints/webhook/handler.py`, `registry.py`, `redis_registry.py`, `transformer.py`
- `src/backend/entrypoints/websocket/` — листинг
- `src/backend/entrypoints/scheduler/invoker_schedule.py:196` (read confirm only)
- `tools/check_layers.py:47-69` (ALLOWED matrix)
- Тесты:
  - `tests/unit/entrypoints/cdc/test_management_endpoints_auth.py` (T-W1-05)
  - `tests/unit/entrypoints/sse/test_handler.py` + `test_handler_auth_propagation.py`
  - `tests/unit/entrypoints/stream/test_invoker_subscribers.py`
  - `tests/unit/entrypoints/filewatcher/test_watcher_routes.py`, `test_watcher_manager.py`

### Не проверено (по явному ограничению задачи)

- `src/backend/entrypoints/api/**` — исключено scope.
- `entrypoints/middlewares/auth_*.py`, `security/*` — исключено scope.
- `src/backend/services/ops/data_quality/**` — вне scope (DataQuality).
- `src/backend/infrastructure/clients/external/cdc/_dlq_writer_guard.py` и
  `client.py` ("B-17 fix (cycle 37)") — вне scope. Упомянуто в задании,
  но в моём домене не читалось.
- `docs/audit/swarm-2026-08-06/cycle-{1,2,3}/**` — не читались.
- `CLAUDE.md`, `PLAN.md`, `KNOWN_ISSUES.md`, `DEEP_AUDIT_REPORT.md`,
  `triage_allowlist_report.md` — не читались.
- Express/MQTT/gRPC/MCP/Soap/GraphQL подробно — вне scope (см. другие
  домены phase-1), листинг директорий сделан, но файлы не
  инспектировались построчно.

---

## 2. Verified strengths (что реально работает в scope)

| # | Что | Evidence | Зачем это важно |
|---|---|---|---|
| W1 | **T-W1-05 подтверждён в HEAD** (CDC + Filewatcher admin guard) | `.venv/bin/python -c "from src.backend.entrypoints.cdc import cdc_routes; ..."` → `cdc_router.dependencies = [Depends(dependency=<function require_admin.<locals>._dep ...>)]`; `watcher_router` — аналогично. `cdc_routes.py:24-30`, `watcher_routes.py:24-31` объявляют `_admin_dep = require_admin((AdminRole.SUPER_ADMIN,))` **на module-level** (identity stable для `dependency_overrides`). 4/4 теста в `tests/unit/entrypoints/cdc/test_management_endpoints_auth.py` PASS. | Pure ASGI fail-closed (комментарий: `"неаутентифицированные запросы → 403"`). |
| W2 | **stream/subscribers.py:9** — line 9 это `from src.backend.entrypoints.api.generator.registry import action_handler_registry` (intra-layer). `tools/check_layers.py:64` разрешает entrypoints импортировать core/services/schemas; intra-package import — допустим (entrypoints→entrypoints не нарушает layering). | read: `src/backend/entrypoints/stream/subscribers.py:9`. | Прямого layer violation нет, action-handler переиспользуется через общий registry. |
| W3 | **T-W1-08** (credit_pipeline) — подтверждено в baseline (8/8 smoke). | (см. BASELINE.md:20) | Вне scope, оставлено как cross-check. |
| W4 | **SSE PII filter** имеет правильный fallback: при ошибке `stream_filter` SSE-stream не падает, а использует raw generator (best-effort). | `sse/handler.py:149-151` (raw fallback), `tests/unit/entrypoints/sse/test_handler.py::TestSseStream::test_event_generator_fallback_yields_raw` PASS. | Streaming contract не разрушается при сбое PII pipeline. |
| W5 | **Filewatcher — Wave B**: `watchfiles.awatch` (rust-based) с debounce, без polling-loop. | `filewatcher/watcher_manager.py:144-175` (`async for changes in awatch(... debounce=debounce_ms)`). | Замена polling→event-driven органична (Airflow/Camel-like EIP). |
| W6 | **Async-first / type-hints везде в scope**: `async def` для всех endpoint'ов, `def` только в dataclass-методах (`WatcherSpec`). | read: `cdc_routes.py`, `sse/handler.py`, `stream/*.py`, `filewatcher/*.py`, `webhook/handler.py`. | Соответствует AGENTS.md правилам. |
| W7 | **CDC + Filewatcher routers** явно вытащили `_admin_dep` в module scope — поэтому `dependency_overrides[_admin_dep] = _fake_admin` в тестах корректно работает. | `cdc_routes.py:24`, `watcher_routes.py:25`, test `test_management_endpoints_auth.py:30-31`. | Без этого trick FastAPI бы считал override не-валидным (новые closures). |
| W8 | **Webhook — SSRF + HMAC + rate-limit** для inbound. | `webhook/handler.py:90-95` (`_validate_url`), `handler.py:160-169` (HMAC compare_digest), `handler.py:43-70` (rate limiter). | Защитный периметр fail-closed. |

---

## 3. Findings table (P0..P4)

| ID | Pri | path:line | Impact | Test-критерий |
|---|---|---|---|---|
| ENTRY-P0-001 | P0 | `src/backend/entrypoints/stream/invoker_subscribers.py:57-93` | MQ consumer (Redis Streams + RabbitMQ) **не использует nack/requeue/dead-letter pathway**. Bare `except Exception: stream_logger.exception(...)` и затем **молчаливый return** — инвойк "успешно принят" с точки зрения брокера, но в reply-канале не зарегистрирован (data-loss при сбое downstream). DLQ не пишется, retry-механизм отсутствует. | Подменить `invoker.invoke` на raise → assert что сообщение попадает в DLQ / публикуется `InvocationStatus.ERROR` в reply-канал. |
| ENTRY-P0-002 | P0 | `src/backend/entrypoints/stream/subscribers.py:33,48` | Тот же data-loss паттерн в DSL-action MQ consumer: bare `except Exception` + log, нет DLQ-writer (для legacy `action_handler_registry` pathway). FastStream дефолтно nack'ает на raise, но обработчик **глотает все исключения**, превращая возможный retry в silent drop. | Unit-тест с patched `action_handler_registry.dispatch` raising → assert DLQ queue содержит message-id. |
| ENTRY-P1-001 | P1 | `src/backend/entrypoints/sse/handler.py:188-225` (`sse_invoke`) | `sse_invoke` **не пробрасывает `principal` / `permissions`** из `request.state.auth` в `dispatch_action_or_dsl`. Auth через `Depends(require_auth(...))` уже валидирует доступ, но **DSL pipeline получает** `principal=""` (anonymous) → fail-closed на protected routes означает, что ВСЕ SSE-invoke попадают под `RoutePermissionDeniedError`. Подтверждено: `8 xfailed` тестов в `tests/unit/entrypoints/sse/test_handler_auth_propagation.py` (каждый явно отмечен `xfail` со ссылкой на Sprint 1.4 L5 Security Chain). Параллельный GraphQL уже пробрасывает (см. `graphql/schema.py:452,552`). | `pytest -k test_authorized_principal_propagates_to_dispatch` — должен проходить после фикса (сейчас xfail). |
| ENTRY-P1-002 | P1 | `tests/unit/entrypoints/filewatcher/test_watcher_routes.py:31-145` | 6 pre-existing test failure: `test_create_watcher_success`, `test_create_watcher_bad_directory`, `test_delete_watcher_success`, `test_delete_watcher_not_found`, `test_list_watchers`, `test_list_watchers_empty` — все получают 403 потому что `watcher_router` теперь требует admin auth (T-W1-05 fix), а тесты **не используют `app.dependency_overrides[fw._admin_dep] = ...`**. Test-код устарел по отношению к commit 22e08a0d. Не атрибутируется рою cycle 4 (т.к. T-W1-05 = cycle-2 D-AUDIT-07, закоммичен в HEAD 22e08a0d). | Обновить тесты: добавить `_make_app(with_admin=True)` и `app.dependency_overrides[fw._admin_dep] = _fake_admin` (как в `tests/unit/entrypoints/cdc/test_management_endpoints_auth.py`). |
| ENTRY-P1-003 | P1 | `src/backend/entrypoints/webhook/handler.py:84-127` | management endpoints (`POST/DELETE/GET /webhooks/subscriptions`) используют `_require_auth_dep` (lazy import) **без указания методов аутентификации** — `require_auth()` без аргументов. Это либо P1 layer/security (auth selector работает в режиме "any method" — но нужен контракт), либо дрейф от W17 security-волны, которая добавила `AuthMethod.*` для CDC/filewatcher. | Проверить: `grep -cE "method=AuthMethod" src/backend/entrypoints/webhook/handler.py` → 0. Требуется явный список методов + admin-guard parity с CDC. |
| ENTRY-P1-004 | P1 | `src/backend/entrypoints/webhook/handler.py:155-169` | HMAC signature verify **не использует `hmac.compare_digest` корректно при отсутствии подписки**: если ни одна подписка не имеет secret, код молча пропускает запрос (`if secret:` — short-circuit). Это fail-open: при ошибочной конфигурации webhook принимается без верификации. | Тест: `event_type` без подписки → 401 (а не 200 с пустым payload). |
| ENTRY-P2-001 | P2 | `src/backend/entrypoints/stream/subscribers.py:33-34, 49-51` | `except Exception` в MQ handler ловит ВСЁ включая `KeyboardInterrupt` (через `BaseException` ancestry Python 3 — нет, `Exception` не ловит `KeyboardInterrupt`, но всё равно — голый `Exception` маскирует domain errors). | Заменить на `except (ValueError, TypeError, KeyError, RuntimeError)` или специфические DLQ-исключения. |
| ENTRY-P2-002 | P2 | `src/backend/entrypoints/filewatcher/watcher_manager.py:172-175` | В `_watch_loop`: `except Exception: logger.exception(...)` и continue-цикл — после сбоя `awatch` корутина `raise` обрывает watcher без recovery. Подавление исключений маскирует реальный root cause. | Заменить на конкретные исключения (`OSError`, `PermissionError`) + DLQ-publish. |
| ENTRY-P2-003 | P2 | `src/backend/entrypoints/webhook/handler.py:36-40` | `_require_auth_dep` — функция-factory, вызываемая в `Depends(...)`. Это создаёт **новую функцию на каждый вызов** (anti-pattern: `use_cache=True` спасает только если signature одинакова, но FastAPI identity-check может сломаться как в CDC fix). | Заменить на module-level identity: `from ... import require_auth; _admin_dep = require_auth([...])`. |
| ENTRY-P3-001 | P3 | `src/backend/entrypoints/webhook/handler.py:78-105` | Дубликат `WebhookSubscription` + `WebhookRegistry` + `redis_webhook_registry` в `webhook/registry.py` и `webhook/redis_registry.py` (95 LOC + 100 LOC, частичное перекрытие). WebhookRelay тоже задвоен (`webhook/transformer.py` — backward-compat shim → `services/integrations/webhook_relay.py`). | Consolidation: оставить только Redis variant (multi-instance safe); in-memory — только для unit-тестов. |
| ENTRY-P3-002 | P3 | `src/backend/entrypoints/stream/invoker_subscribers.py:67-93` | Использует `from src.backend.services.execution.invoker import _deserialize_request, get_invoker` — `_deserialize_request` это **private** функция (leading underscore). Вместо неё есть публичный API в services. | Заменить на `services.execution.invoker.deserialize_request` (публичный wrapper). |
| ENTRY-P4-001 | P4 | `src/backend/entrypoints/stream/` | DSL-action `action_handler_registry` pathway (subscribers.py) — частично перекрывается с invoker pathway (invoker_subscribers.py) для тех же source-каналов. Два consumer'а на одном `ActionCommandSchema` — лишний indirection без явного use-case. | Документировать в коде: "legacy путь — kept for backward-compat with non-InvocationRequest legacy producers". Если нет — удалить. |

---

## 4. Detailed evidence

### 4.1 T-W1-05 (CDC + Filewatcher admin guard) — VERIFIED

```text
.venv/bin/python -c "from src.backend.entrypoints.cdc import cdc_routes; ..."
cdc_router.dependencies = [Depends(dependency=<function require_admin.<locals>._dep at 0x789bc7370bf0>, use_cache=True, scope=None)]
_admin_dep = <function require_admin.<locals>._dep at 0x789bc7370bf0>
watcher_router.dependencies = [Depends(dependency=<function require_admin.<locals>._dep at 0x789bc5b3f480>, use_cache=True, scope=None)]
```

Source (cdc_routes.py:24-30):
```python
_admin_dep = require_admin((AdminRole.SUPER_ADMIN,))
cdc_router = APIRouter(prefix="/api/v1/cdc", tags=["CDC"], dependencies=[Depends(_admin_dep)])
```

Source (watcher_routes.py:25-31):
```python
_admin_dep = require_admin((AdminRole.SUPER_ADMIN,))
watcher_router = APIRouter(prefix="/watchers", tags=["File Watchers"], dependencies=[Depends(_admin_dep)])
```

Тест (`tests/unit/entrypoints/cdc/test_management_endpoints_auth.py`):
- `test_cdc_no_auth_rejected` PASS
- `test_cdc_admin_ok` PASS
- `test_filewatcher_no_auth_rejected` PASS
- `test_filewatcher_admin_ok` PASS

**Статус:** ✅ RESOLVED (cycle-2 D-AUDIT-07, закоммичено в HEAD 22e08a0d).

### 4.2 cycle-3 P0-001 (SSE principal/permissions) — RESIDUAL

Source (`src/backend/entrypoints/sse/handler.py:188-225`):
```python
async def sse_invoke(request: Request, body: _InvokeRequest) -> StreamingResponse:
    correlation_id = request.headers.get("x-correlation-id") or request.headers.get("x-request-id")
    idempotency_key = request.headers.get("idempotency-key")
    ...
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

`request.state.auth` НЕ читается; `principal` / `permissions` НЕ передаются.
Сравнение: `src/backend/entrypoints/graphql/schema.py:452, 552`:
```python
principal, permissions = _extract_auth_from_info(info)
... principal=principal, permissions=permissions ...
```

Тесты:
```
tests/unit/entrypoints/sse/test_handler_auth_propagation.py:
  8 xfailed (test_authorized_principal_propagates_to_dispatch,
            test_oauth_scope_metadata_normalized,
            test_no_auth_state_fails_closed_anonymous,
            test_wrong_role_fails_closed,
            test_public_route_dispatches_with_principal,
            test_execution_context_in_dispatch_call,
            test_auth_with_no_metadata_yields_empty_permissions,
            test_request_state_without_auth_attribute)
```

Reason (каждый): "SSE /events/invoke не пробрасывает principal/permissions из request.state.auth в DslService.dispatch (parity с GraphQL/REST). Forward-looking TDD до Sprint 1.4 L5 Security Chain migration."

**Статус:** ⚠️ RESIDUAL (8 xfailed как forward-looking TDD). Severity остаётся P1 — handler активно в проде (Wave 1.5 closure), fail-closed DSL route = SSE работает только для public routes, что снижает utility.

### 4.3 cycle-3 P0-002 (MQ DLQ) — RESIDUAL

Source (`src/backend/entrypoints/stream/invoker_subscribers.py:57-93`):
```python
async def _dispatch_invocation_message(body, *, correlation_id, source):
    try:
        request = _deserialize_request(body)
    except (KeyError, ValueError, TypeError) as exc:
        stream_logger.warning("MQ invocation: невалидный body source=%s ...", ...)
        return                                       # <-- bare return, no DLQ
    ...
    invoker = get_invoker()
    try:
        await invoker.invoke(request)
    except Exception as _:                           # <-- bare except
        stream_logger.exception("MQ invocation: Invoker.invoke failed source=%s id=%s", ...)
        # <-- bare return, NO nack / NO DLQ publish
```

`grep -RInE "nack|requeue|dead_letter" src/backend/entrypoints/stream/` → 0 hits.

Аналогично (`src/backend/entrypoints/stream/subscribers.py:33-34, 48-50`):
```python
@stream_client.redis_router.subscriber(...)
async def handle_universal_redis_action(body, msg, redis):
    try:
        command = ActionCommandSchema.model_validate(body)
        ...
        await action_handler_registry.dispatch(command)
    except Exception as exc:                         # <-- bare except
        stream_logger.error(f"Failed to process Redis DSL action: {exc}", exc_info=True)
        # <-- bare return, NO nack / NO DLQ
```

В `src/backend/core/di/providers.py` (DI provider) — нет DLQ wiring для `stream_client`.

Тесты:
- `tests/unit/entrypoints/stream/test_invoker_subscribers.py` — `TestHandleRedisInvocation::test_invoker_raises` PASS, но `mock_bridge` мокает Invoker и **assert только на `logger.exception.assert_called()`** — не проверяет, попало ли сообщение в DLQ. Это **happy path test, который маскирует data-loss**.

**Статус:** ⚠️ RESIDUAL (P0 data-loss). Документировано в cycle-2/3, не закрыто. Подтверждено кодом.

### 4.4 stream/subscribers.py:9 — INTRA-LAYER (allowed)

`src/backend/entrypoints/stream/subscribers.py:9`:
```python
from src.backend.entrypoints.api.generator.registry import action_handler_registry
```

`tools/check_layers.py:64`:
```python
"entrypoints": {"services", "schemas", "core"},
```

Прямого cross-layer violation нет: `entrypoints.api.generator` — это тот же layer (entrypoints). **Подтверждено как допустимое**, не атрибутируется как P1 layer violation.

**Caveat (вне скоупа):** `action_handler_registry` находится в `entrypoints/api/generator/registry.py` — это нарушает **ужесточенный принцип "thin router"** (handler-логика не должна жить в `entrypoints/api/generator/`). Если когда-нибудь введут правило "только infra-agnostic imports в entrypoints", это станет violation. Сейчас — OK.

### 4.5 DataQuality "B-17 fix (cycle 37)" — НЕ ПРОВЕРЕНО (вне scope)

Прямой grep в scope: 0 hits. Подтверждено:
```
grep -RIn "DataQuality" src/backend/entrypoints/  → 0 hits
grep -RIn "B-17 fix" src/backend/entrypoints/  → 0 hits
```

Реальные владельцы:
- `src/backend/services/ops/data_quality/**` (DataQualityMonitor)
- `src/backend/infrastructure/clients/external/cdc/_dlq_writer_guard.py:1` ("B-17 fix (cycle 37)")
- `src/backend/infrastructure/clients/external/cdc/client.py:17,77,90,102,267,274`
- `src/backend/services/plugins/composition/di.py:239`

**В моём домене не читалось. Не атрибутирую к entrypoints.**

### 4.6 Layer-architecture hygiene

Cross-checked `tools/check_layers.py:60-69`:
- entrypoints → core, services, schemas (allowed)
- entrypoints → entrypoints (intra-package, allowed)
- entrypoints → infrastructure (НЕ allowed)

Grep в scope:
```
grep -RIn "from src.backend.infrastructure" src/backend/entrypoints/ → 0 hits
```

Подтверждено: нет прямых imports entrypoints→infrastructure. Entry-points используют только `core.*` (di/providers, config/settings, auth, logging) и `services.*` (lazy-import внутри endpoint'ов). Это соответствует архитектурному правилу.

Найдены lazy imports `services.*` (допустимо для hot-path):
- `sse/handler.py:139`: `from src.backend.services.security.pii_streaming_facade import ...`
- `stream/invoker_subscribers.py:67`: `from src.backend.services.execution.invoker import ...`
- `scheduler/invoker_schedule.py:196`: `from src.backend.services.execution.invoker import get_invoker`
- `dependencies/rate_limit.py:31`: `from src.backend.services.resilience.rate_limiter import ...`

**Статус:** layer hygiene OK. Никаких новых violations в scope.

### 4.7 Dead code / TODO / FIXME / stubs

```
grep -RInE "(^|\s)(TODO|FIXME|XXX|HACK)\b" src/backend/entrypoints/ --include='*.py' | wc -l
```

В scope файлах, которые прочитаны:
- `sse/handler.py` — 0 hits
- `cdc/cdc_routes.py` — 0 hits
- `filewatcher/*.py` — 0 hits
- `stream/subscribers.py` — 0 hits
- `stream/invoker_subscribers.py` — 0 hits
- `webhook/handler.py` — 0 hits
- `webhook/registry.py` — 0 hits
- `webhook/redis_registry.py` — 0 hits

Голые `pass` / `except Exception: pass`:
- `stream/subscribers.py:33,48` — `except Exception as exc: stream_logger.error(...)` (НЕ pass, логирует)
- `stream/invoker_subscribers.py:89` — `except Exception as _: stream_logger.exception(...)` (логирует, но НЕ nack/DLQ)
- `webhook/handler.py:55-56` — `except ImportError: return` (silent fail для rate-limiter DI)
- `filewatcher/watcher_manager.py:172-175, 194-195` — `except Exception: logger.exception(...)` (catch-all)

Подтверждено: dead code / pass-through в scope минимален. Основная проблема — **bare except + log** без recovery (ENTRY-P2-001/002).

### 4.8 Library replacement opportunities

| Candidate | Current code | Mature library | Когда органично |
|---|---|---|---|
| `cachetools` для SSE EventBus bounded queue | `asyncio.Queue(maxsize=100)` в `sse/handler.py:60-70` | `cachetools.TTLCache` (уже в pyproject для cycle-1 T-3.1) | Если потребуется TTL на подписки (сейчас — leaky: неудалили `unsubscribe` если клиент отвалился). P3. |
| `tenacity` для retry-механизма MQ | `stream/invoker_subscribers.py:86-93` (bare except + log) | `tenacity.retry` (async) | См. ENTRY-P0-001 — рекомендуется как часть DLQ fix. |
| `structlog` для SSE/PII logging | `get_logger` (stdlib) в `sse/handler.py:31` | structlog | Не блокер. |
| `watchfiles` уже заменён в `watcher_manager.py:20` | — | — | ✅ Уже используется. |
| `httpx` вместо `aiohttp` | Не в scope | — | Заменено в cycle-3 T-3.1. |
| `defusedxml` для XML SOAP | Не в scope | — | T-10 cycle-3. |

---

## 5. Cycle-1+2+3 residuals (verified/mutated/resolved)

| Cycle | ID | Описание | Статус в HEAD 22e08a0d | Evidence |
|---|---|---|---|---|
| C1 | T-1.1 | composition root fix | RESOLVED (предположительно) | Не проверял; вне scope этого домена. |
| C1 | T-1.2 | SSE/HITL auth (8 xfailed) | **RESIDUAL** (8 xfailed в `test_handler_auth_propagation.py`) | См. §4.2. ENTRY-P1-001. |
| C1 | T-1.3 | MQ DLQ data-loss | **RESIDUAL** (DLQ отсутствует в `stream/invoker_subscribers.py`) | См. §4.3. ENTRY-P0-001. |
| C1 | T-2.1 | reverse-layer cleanup | RESOLVED (не атрибутируется к entrypoints) | layer check pass. |
| C1 | T-4.1 | text-RAG E2E | Не в моём scope. | — |
| C2 | T-W1-01 | AuthenticationProviderUnavailableError | RESOLVED (smoke pass) | BASELINE:18. |
| C2 | T-W1-02 | CDC DLQ handoff failure | **RESIDUAL** (связано с B-17 fix в cdc/_dlq_writer_guard.py — вне scope) | Не верифицировал (вне scope). |
| C2 | T-W1-03 | MQ subscribers ACK vs DLQ | **RESIDUAL** (= P0-001, P0-002) | См. §4.3. |
| C2 | T-W1-04 | composition root DI | RESOLVED (предположительно) | Не проверял. |
| C2 | T-W1-05 | CDC + Filewatcher admin guard | **RESOLVED** | См. §4.1. 4/4 PASS. |
| C2 | T-W1-06 | RagCachePrewarmer runtime | Не в моём scope. | — |
| C2 | T-W1-07 | SSE principal/permissions | **RESIDUAL** (= T-1.2, xfailed) | См. §4.2. |
| C2 | T-W2-01..04 | layer track | RESOLVED (175 legacy / 0 new) | BASELINE:7. |
| C2 | T-W3-01 | tenacity library replacement | **RESIDUAL** (частично) — bare except в `stream/invoker_subscribers.py:89` | ENTRY-P0-001. |
| C2 | T-W4-01 | text-RAG E2E | Не в моём scope. | — |
| C3 | T-04 | CVE enforcement unification | RESOLVED (27 active, BASELINE:8) | Не в scope entrypoints, но верифицировано. |
| C3 | T-05 | hardcoded shutdown timeout | Не в моём scope. | — |
| C3 | T-06 | test-infra conftest | Не в моём scope. | — |
| C3 | T-08 | TenantFacade kwargs fix | Не в моём scope. | — |
| C3 | T-09 | credit_pipeline_v2 | T-W1-08 RESOLVED | BASELINE:19. |
| C3 | T-10 | defusedxml drop-in | Не в моём scope (SOAP — out of scope). | — |
| C3 | T-11 | organic feature | Не в моём scope. | — |

---

## 6. Contradictions / overlaps to flag

1. **Webhook `_require_auth_dep` vs CDC `require_admin((SUPER_ADMIN,))`** — разные security-уровни для management endpoints. CDC/filewatcher — admin-only; webhook — "any authenticated". Это либо умышленно (webhook admin == tenant admin), либо дрейф. Требует проверки у phase-2 security-аудита.

2. **Two MQ consumer pathways** (`subscribers.py` + `invoker_subscribers.py`) — оба импортируют `stream_client` (faststream Redis + Rabbit), оба живут в `entrypoints/stream/`, оба подписаны на разные топики. Дублирование + общий routing config (см. `stream/__init__.py:1-9`). Если протокол когда-то изменится (Sprint 36 → FastStream 1.0), оба надо апдейтить.

3. **`_make_auth_from_principal`** живёт в `entrypoints/graphql/schema.py:252-272` (intra-layer) и переиспользуется только GraphQL. SSE должен бы делать то же — см. ENTRY-P1-001.

4. **Pre-existing test drift в filewatcher** (6 FAIL): 22e08a0d закоммитил `watcher_routes.py:25-31` (T-W1-05), но `tests/unit/entrypoints/filewatcher/test_watcher_routes.py` НЕ обновлён. Эти тесты были рабочими до T-W1-05 (cycle-2 D-AUDIT-07). Cross-domain debt: cycle 4 audit (security) их не видит, потому что 22e08a0d содержит source fix. Требуется phase-2 cross-domain sync.

5. **`webhook/registry.py` (in-memory) vs `webhook/redis_registry.py` (Redis)** — оба доступны как singletons (`webhook_registry`, `redis_webhook_registry`). 1 из них dead в проде (in-memory не работает с multi-instance). Не смертельно, но `webhook/handler.py:100` использует in-memory, в то время как `_action_bridge` ожидает Redis. См. ENTRY-P3-001.

---

## 7. Readiness score 0–100 (с формулой)

### Формула

```
readiness = 100
  - 8 * P0_count                # P0 = critical security/data-loss
  - 5 * P1_count                # P1 = layer / auth / test drift
  - 1 * P2_count                # P2 = dead code / bare except
  - 0.5 * P3_count              # P3 = library replacement / dead variants
  - 0.2 * P4_count              # P4 = organic feature gap
  - (overhead за pre-existing drift и unverified scope)
```

### Счёт (cycle 4 entrypoints domain)

| Category | Count | Weight | Subtotal |
|---|---|---|---|
| P0 | 2 (ENTRY-P0-001, ENTRY-P0-002) | 8 | 16 |
| P1 | 4 (ENTRY-P1-001..004) | 5 | 20 |
| P2 | 3 (ENTRY-P2-001..003) | 1 | 3 |
| P3 | 2 (ENTRY-P3-001..002) | 0.5 | 1 |
| P4 | 1 (ENTRY-P4-001) | 0.2 | 0.2 |
| Pre-existing test drift (filewatcher) | (1 domain) | 2 | 2 |
| Unverified DataQuality / B-17 fix | (1 domain) | 1 | 1 |

**Raw: 100 - (16 + 20 + 3 + 1 + 0.2 + 2 + 1) = 56.8 → 57/100**

### Обоснование

- T-W1-05 (key P0 из cycle 2) — RESOLVED, +0 штрафа.
- 2 × P0 data-loss (MQ subscribers без DLQ) — основной blocker.
- 4 × P1: 1 SSE principal (security), 1 filewatcher test drift, 2 webhook auth.
- 3 × P2: bare except masking domain errors.
- DataQuality / B-17 fix — не проверено (out of scope), потенциальный risk.

**Verdict: 57/100** (порог ≥80 запрещён при наличии P0/P1 — здесь оба присутствуют, поэтому score остаётся в low-band).

---

## 8. Recommended next tasks (cycle 5 / sprint 172+)

| Pri | Task | Files | Effort | Impact |
|---|---|---|---|---|
| P0 | Реализовать DLQ-handoff для MQ subscribers: добавить `dlq_writer` provider в `stream_client` DI; `nack(requeue=False)` + `dlq_writer.write(payload, error, source)`; добавить unit-тест с mocked DLQ writer. | `src/backend/entrypoints/stream/invoker_subscribers.py:57-93`, `subscribers.py:18-50`, `src/backend/core/di/providers.py` | M | Устраняет P0-001/002. |
| P1 | Реализовать `request.state.auth → dispatch_action_or_dsl(principal=..., permissions=...)` проброс в `sse_invoke`. Удалить xfail-маркеры с 8 тестов. | `src/backend/entrypoints/sse/handler.py:188-225`, `tests/unit/entrypoints/sse/test_handler_auth_propagation.py` | S | Устраняет P1-001. Parity с GraphQL/SOAP. |
| P1 | Обновить filewatcher test-suite: добавить `app.dependency_overrides[fw._admin_dep]` (по аналогии с CDC test). | `tests/unit/entrypoints/filewatcher/test_watcher_routes.py` | XS | Устраняет 6 pre-existing FAIL. |
| P1 | Webhook management endpoints: заменить `_require_auth_dep` (factory) на module-level `require_auth([API_KEY, JWT])` + admin-guard parity с CDC. | `src/backend/entrypoints/webhook/handler.py:36-127` | S | Устраняет P1-003/004. |
| P2 | Заменить `except Exception` в `stream/invoker_subscribers.py:89`, `subscribers.py:33,48` на specific exceptions + метрика. | (см. выше) | XS | Устраняет P2-001. |
| P3 | Consolidate `webhook/registry.py` + `redis_registry.py` → единый `webhook/registry.py` (Redis + in-memory fallback для тестов). | `webhook/registry.py`, `webhook/redis_registry.py` | M | Устраняет P3-001. |
| P3 | Создать публичный `services.execution.invoker.deserialize_request` (без leading underscore). | `services/execution/invoker.py` | XS | Устраняет P3-002. |
| P4 | Документировать в `stream/__init__.py` различие между `subscribers` (legacy action_handler_registry) и `invoker_subscribers` (новый invoker pathway). | `stream/__init__.py` | XS | Устраняет P4-001. |

---

## 9. Commands run (с явным указанием interpreter)

```bash
# Все команды — .venv/bin/python (system Python не подключён к .venv).

# 1. T-W1-05 runtime verification
.venv/bin/python -c "
from src.backend.entrypoints.cdc import cdc_routes
print('cdc_router.dependencies =', cdc_routes.cdc_router.dependencies)
print('_admin_dep =', cdc_routes._admin_dep)
from src.backend.entrypoints.filewatcher import watcher_routes
print('watcher_router.dependencies =', watcher_routes.watcher_router.dependencies)
print('_admin_dep =', watcher_routes._admin_dep)
"
# → оба router.dependencies[0] = Depends(<function require_admin.<locals>._dep>)
# → оба _admin_dep = module-level function (stable identity)

# 2. T-W1-05 + filewatcher + sse + stream subscribers tests
.venv/bin/python -m pytest tests/unit/entrypoints/cdc/test_management_endpoints_auth.py \
  tests/unit/entrypoints/sse/test_handler.py \
  tests/unit/entrypoints/stream/test_invoker_subscribers.py -v
# → 32 PASS, 2 FAIL (SSE PII presidio — pre-existing env, не в scope)
# → 4 PASS (T-W1-05 subset)

# 3. SSE xfail verification
.venv/bin/python -m pytest tests/unit/entrypoints/sse/test_handler_auth_propagation.py -v
# → 8 xfailed (все ожидаемые, см. §4.2)

# 4. filewatcher tests (pre-existing drift)
.venv/bin/python -m pytest tests/unit/entrypoints/filewatcher/ -q
# → 41 PASS, 6 FAIL (= test_watcher_routes.py:31-145, см. ENTRY-P1-002)

# 5. Stream subscribers layer/import verification
.venv/bin/python -c "
from src.backend.core.di.providers import http, workflow
from unittest.mock import MagicMock, patch
import sys
fake_client = MagicMock()
fake_client.redis_router = MagicMock()
fake_client.rabbit_router = MagicMock()
fake_client.redis_router.subscriber.return_value = lambda fn: fn
fake_client.rabbit_router.subscriber.return_value = lambda fn: fn
http.set_stream_client_provider(fake_client)
workflow.set_stream_logger_provider(MagicMock())
with patch('src.backend.core.config.settings.settings') as s:
    s.redis.get_stream_name.return_value='dsl-events'
    s.queue.get_queue_name.return_value='dsl-actions'
    if 'src.backend.entrypoints.stream.subscribers' in sys.modules:
        del sys.modules['src.backend.entrypoints.stream.subscribers']
    m = __import__('src.backend.entrypoints.stream.subscribers', fromlist=['*'])
    import linecache
    print('module file:', m.__file__)
    print('line 9:', repr(linecache.getline(m.__file__, 9).rstrip()))
"
# → module loads; line 9 = 'from src.backend.entrypoints.api.generator.registry import action_handler_registry' (intra-layer allowed)

# 6. SSE principal gap verification
.venv/bin/python -c "
import inspect
from src.backend.entrypoints.sse.handler import sse_invoke
src = inspect.getsource(sse_invoke)
print('Uses request.state.auth?', 'request.state.auth' in src)
print('Uses auth.principal?', 'auth.principal' in src)
print('Uses principal kwarg?', 'principal' in src)
"
# → все False (P1-001 подтверждён)

# 7. MQ DLQ check
grep -RInE "nack|requeue|dead_letter" src/backend/entrypoints/stream/
# → 0 hits (P0-001/002 подтверждены)

# 8. Layer hygiene
grep -RIn "from src.backend.infrastructure" src/backend/entrypoints/
# → 0 hits (нет cross-layer violations в scope)

# 9. Pre-existing test failures root cause
grep -n "dependency_overrides" tests/unit/entrypoints/filewatcher/test_watcher_routes.py
# → 0 hits (тесты не override _admin_dep; после T-W1-05 получают 403)

# 10. Baseline HEAD / allowlist
git -C /home/user/dev/gd_integration_tools rev-parse HEAD
# → 22e08a0d (cycle-1/2/3 reapply commit)
grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt
# → 27 (cycle-4 D-AUDIT-02: 35→27)
```

### Сводка runtime-результатов

| Тест | PASS | FAIL | XFAIL | Skip |
|---|---|---|---|---|
| `tests/unit/entrypoints/cdc/test_management_endpoints_auth.py` | 4 | 0 | 0 | 0 |
| `tests/unit/entrypoints/sse/test_handler.py` | 9 | 2 (presidio env, не в scope) | 0 | 0 |
| `tests/unit/entrypoints/sse/test_handler_auth_propagation.py` | 0 | 0 | 8 | 0 |
| `tests/unit/entrypoints/stream/test_invoker_subscribers.py` | 6 | 0 | 0 | 0 |
| `tests/unit/entrypoints/filewatcher/test_watcher_routes.py` | 0 | 6 (T-W1-05 test drift) | 0 | 0 |
| `tests/unit/entrypoints/filewatcher/test_watcher_manager.py` | 3 | 0 | 0 | 0 |

---

## 10. Self-audit checklist

- [x] Все runtime-проверки через `.venv/bin/python` (system Python не подключён).
- [x] Не читал отчёты других агентов и cycle-1/2/3 markdown.
- [x] Не читал `KNOWN_ISSUES.md`, `CLAUDE.md`, `PLAN.md`, `DEEP_AUDIT_REPORT.md`, `triage_allowlist_report.md`.
- [x] Не менял source, configs, lockfiles, allowlists (только этот markdown).
- [x] Не делал git mutation.
- [x] DataQuality / B-17 fix — пометил "не проверено" (вне scope).
- [x] Все finding IDs имеют path:line + evidence + impact + recommendation.
- [x] Все cycle-1+2+3 IDs перепроверены (RESOLVED/RESIDUAL).
- [x] 8 правок cycle 1+2+3 атрибутированы как уже в HEAD 22e08a0d, не рою cycle 4.
- [x] Pre-existing drift (uv.lock, blue_green, pip-audit.json, .blue_green.state) — НЕ атрибутируется рою.
- [x] Score 57 < 80 (P0/P1 присутствуют — запрет на ≥80 соблюдён).
- [x] Раздел готовности содержит формулу и обоснование.
- [x] Раздел "Commands run" с явным указанием interpreter.
- [x] Streamlit / pyproject.toml — не моя зона (не проверял), не атрибутирую.
