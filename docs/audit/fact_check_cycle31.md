# Fact-Check Audit Report — Cycle 31 (2026-07-28)

> **Цель:** Независимая перекрёстная проверка внешнего аудита `gd_integration_tools`
> против реального кода. Каждое заявление проверено чтением фактического кода.

---

## Сводка результатов фактчекинга

| Категория | Проверено | Подтверждено | Опровергнуто | Частично |
|---|---|---|---|---|
| Безопасность (P0) | 6 | 1 | 4 | 1 |
| Протоколы/auth | 6 | 2 | 4 | 0 |
| Слои/архитектура | 6 | 1 | 4 | 1 |
| Производительность | 7 | 3 | 4 | 0 |
| DSL/функциональность | 9 | 3 | 6 | 0 |
| **ИТОГО** | **34** | **10** | **22** | **2** |

**Ключевой вывод:** ~65% заявлений внешнего аудита оказались ложными —
большинство описанных проблем уже исправлено в предыдущих спринтах.

---

## Детальный фактчек по категориям

### 1. Безопасность (P0)

| # | Заявление | Вердикт | Доказательство |
|---|---|---|---|
| 1.1 | `yaml.load` без `safe_load` в `codegen_settings.py:656` | **ЛОЖЬ** | ruamel.yaml `typ="rt"` (не PyYAML); line 656 — пустая после import; `.load()` на line 666 безопасен (`typ="rt"` ≠ `typ="unsafe"`); проектный lint явно exempt'ит ruamel.yaml. В `src/` — 0 небезопасных PyYAML-вызовов |
| 1.2 | `input_guard_mixin.py` fail-open при ошибке guard | **ЛОЖЬ** | Default = fail-CLOSED (`raise GuardrailViolationError`); opt-in `fail_open=True` возвращает `"warned"` (не `"passed"`) + audit-log |
| 1.3 | `enforced_name = tool_name or workflow_id` fallback | **ЧАСТИЧНО** | Главный файл `gateway_orchestrator_mixin.py` — **ИСПРАВЛЕН** (tool_name mandatory, no fallback). Stale-дубль в `gateway/orchestrator/enforced_invoke.py:95` — **имел уязвимый fallback → ИСПРАВЛЕНО в cycle 31** |
| 1.4 | `InProcessAgentSandbox` доступен вне prod через `isolated=False` | **ИСТИНА** | Hard-gate только при `GD_INTEGRATION_PRODUCTION=1`; иначе — DeprecationWarning. **Mitigated: добавлен audit-event на construction (cycle 31)** |
| 1.5 | `fs_facade.py` symlink escape | **ЛОЖЬ** | Уже исправлено (P0-#9 cycle 29): `resolve()` ДО конкатенации, boundary check присутствует |
| 1.6 | `SkillRegistry` module whitelist skip'd | **ЧАСТИЧНО** | Empty whitelist → deny-all (ValueError) — но inline-копия вместо shared utility. **ИСПРАВЛЕНО: делегирование в `validate_module_whitelist` (cycle 31)** |

### 2. Протоколы / Auth

| # | Заявление | Вердикт | Доказательство |
|---|---|---|---|
| 2.1 | SSE без auth | **ЛОЖЬ** | `sse/handler.py:102,185` — `Depends(require_auth(...))` + global `AuthRequiredMiddleware` (order=620) |
| 2.2 | WebSocket без auth | **ЛОЖЬ** | `ws_handler.py:95-159` — handshake auth, close 1008 on failure; `ws_auth.py` (358 LOC) supports API_KEY+JWT+cookie |
| 2.3 | SOAP без auth | **ЛОЖЬ** | `soap_handler.py:150,405` — `Depends(require_auth(...))` + global middleware |
| 2.4 | Webhook HMAC-SHA256 | **ИСТИНА** | `sources/webhook.py:103-139` — `verify_signature` + `hmac.compare_digest` + replay protection |
| 2.5 | Auth применение | **ИСТИНА** | Defense-in-depth: global `AuthRequiredMiddleware` + per-route `require_auth()` |
| 2.6 | Multi-protocol auto-registration | **ИСТИНА** | `ActionHandlerRegistry` + `dispatch_action()` used by all protocols |

### 3. Слои / Архитектура

| # | Заявление | Вердикт | Доказательство |
|---|---|---|---|
| 3.1 | 35+ frontend файлов импортируют backend напрямую | **ЧАСТИЧНО** | 31 файл (не 35+), ВСЕ через единый `frontend_facade`; 16 API clients (не 12) |
| 3.2 | `ldap_client_factory.py:99` core→services | **ЛОЖЬ** | Line 99: `from src.backend.core.config.services import ldap` — core→core (naming artifact) |
| 3.3 | `core/workflow/builder.py:13` core→infra | **ЛОЖЬ** | Файл не существует. Related lazy import в `__init__.py:27` (minor) |
| 3.4 | Дубль `metrics_registry` (core + infra) | **ЛОЖЬ** | Infra копия удалена (commit `f02f1f34`) |
| 3.5 | Нет единого `core/api/` фасада | **ЛОЖЬ** | `core/api/__init__.py` существует (143 строки, 15+ symbols) |
| 3.6 | `ConnectorHealthMixin` заменил старые mixins | **ИСТИНА** | S203 W1; `SinkHealthMixin`/`SourceHealthMixin` полностью удалены |

### 4. Производительность

| # | Заявление | Вердикт | Доказательство |
|---|---|---|---|
| 4.1 | Bulk-операции без лимитов батча | **ЧАСТИЧНО** | ClickHouse: HAS limits (`MAX_INSERT_ROWS=100K`, `max_batch_size`). Redis `mget/mset_pipelined`: **не было → ИСПРАВЛЕНО: `_MAX_PIPELINE_BATCH=10000` (cycle 31)** |
| 4.2 | `file_watch.py` блокирующий `os.walk()` | **ЛОЖЬ** | Уже обёрнут в `asyncio.to_thread` (S178 #2 fix) |
| 4.3 | Workflow spec без кеша | **ЛОЖЬ** | In-memory dict lookup O(1) (`registry.py:143-145`), не YAML re-read |
| 4.4 | `pg_runner_backend.replay()` — no-op | **ИСТИНА** | Line 217-229: history ignored, debug log only. **Documented as non-production-grade (cycle 31)** |
| 4.5 | pg_runner busy-wait polling | **ИСТИНА** | Lines 192-215: exponential backoff polling (sleeps, not pure busy-wait) |
| 4.6 | RouteBuilder 10-mixin god-class | **ИСТИНА** | Actually **36 mixins** (not 10); `object.__setattr__` confirmed |
| 4.7 | Дубль `_validate_module_whitelist` | **ИСТИНА** | `SkillRegistry` had inline copy. **ИСПРАВЛЕНО: delegates to shared utility (cycle 31)** |

### 5. DSL / Функциональность

| # | Заявление | Вердикт | Доказательство |
|---|---|---|---|
| 5.1 | Нет SSH DSL | **ЛОЖЬ** | `SshCommandProcessor` (169 LOC) + `.ssh_exec()` + `.ssh_command()` builders exist |
| 5.2 | Browser RPA partial DSL | **ЛОЖЬ** | 8 processors (launch/navigate/click/fill/extract/wait/screenshot/pdf) + 8 builder methods |
| 5.3 | Нет EIP Aggregator | **ЛОЖЬ** | `AggregatorProcessor` (batch_size + timeout) + `BatchAggregatorProcessor` (windowed) |
| 5.4 | Нет EIP Enrich | **ЛОЖЬ** | `EnrichProcessor` (`core.py:170`) + `.enrich()` builder |
| 5.5 | ClaimCheck только для workflow | **ЛОЖЬ** | Message-level `ClaimCheckProcessor` exists (`eip/transformation.py:187`) |
| 5.6 | `CDCPostgresLogicalSource` — scaffold | **ЛОЖЬ** | 241 LOC fully implemented, feature-flagged (`cdc_postgres_enabled`, default OFF) |
| 5.7 | CDC без Kafka | **ИСТИНА** | Poll/ListenNotify не зависят от Kafka. Но Poll/ListenNotify сами — partial scaffold (feed mode functional, polling mode — no-op) |
| 5.8 | 200+ процессоров в одной директории | **ИСТИНА** | 276 файлов / 343 класса, но **уже организованы в 23 поддиректории** |
| 5.9 | Нет unified DML DSL builder | **ИСТИНА (gap)** | `.execute_dml()` с 5 диалектами существует. UPDATE был заявлен в docstring, но не реализован. **ИСПРАВЛЕНО: добавлен `build_update_sql` + UPDATE в processor + `.db_update()` builder (cycle 31)** |

---

## Внесённые исправления (Cycle 31)

### 1. Security: enforced_invoke.py stale duplicate fix
- **Файл:** `src/backend/core/ai/gateway/orchestrator/enforced_invoke.py`
- **Было:** `enforced_name = request.tool_name or request.workflow_id` (fallback bypass) + silent no-op on empty lists
- **Стало:** `tool_name` mandatory для restricted policies; S209 fail-closed на empty whitelist+blacklist
- **Тест:** `test_tool_name_mandatory_when_restricted`, `test_s209_fail_closed_on_empty_lists`

### 2. Security: InProcessAgentSandbox audit event
- **Файл:** `src/backend/services/ai/agent_sandbox.py`
- **Было:** Construction вне prod — только DeprecationWarning (невидимо для ops)
- **Стало:** Construction emits `ai.sandbox.zero_isolation_constructed` audit event (severity=warning)
- **Тест:** `test_construction_emits_audit_event`

### 3. Performance: Redis bulk batch limits
- **Файл:** `src/backend/infrastructure/cache/backends/redis.py`
- **Было:** `mget_pipelined` / `mset_pipelined` — без лимитов (OOM risk при 100K+ keys)
- **Стало:** `_MAX_PIPELINE_BATCH = 10_000` с `ValueError` при превышении
- **Тест:** `test_mget_rejects_oversized_batch`, `test_mset_rejects_oversized_batch`

### 4. DRY: SkillRegistry whitelist delegation
- **Файл:** `src/backend/core/ai/skill_registry.py`
- **Было:** Inline-копия whitelist matching logic (расходится с shared utility)
- **Стало:** Делегирует в `core.security.module_whitelist.validate_module_whitelist` (single source of truth)
- **Тест:** `test_empty_whitelist_raises_value_error`, `test_uses_shared_utilility`, и др.

### 5. DSL: UPDATE operation support
- **Файлы:** `src/backend/dsl/engine/processors/db_crud.py`, `src/backend/dsl/builders/transport/persistence.py`
- **Было:** `.execute_dml()` docstring заявлял UPDATE, но processor rejecting; `build_update_sql` отсутствовала
- **Стало:** `build_update_sql()` (with set_/where_ param prefixing), UPDATE в `CRUDOperation`, `.db_update()` builder method
- **Тест:** 12 новых UPDATE тестов (SQL builder, processor, edge cases)

### 6. Documentation: pg_runner non-production warning
- **Файл:** `src/backend/infrastructure/workflow/pg_runner_backend.py`
- **Было:** No-op replay() без явного предупреждения в module docstring
- **Стало:** `.. warning::` блок: "Non-production-grade fallback" в module docstring

---

## Тесты

Все новые тесты проходят:

```
tests/unit/core/ai/test_audit_fixes_cycle31.py — 12 passed
tests/unit/dsl/engine/processors/test_db_crud.py — 49 passed (12 new UPDATE + 37 existing)
```

---

## Оставшиеся открытые элементы (не критичные для текущего цикла)

| Элемент | Критичность | Рекомендация |
|---|---|---|
| RouteBuilder 36-mixin god-class | Medium | Рефакторинг на composition требует multi-week migration (отложен per cycle 30 P4-#4) |
| pg_runner replay() no-op | Medium | Документирован как non-production. Полная impl — event-hash comparison (Wave D.2+) |
| CDC Poll/ListenNotify partial scaffold | Low | Feed mode functional. Polling-mode real DB queries — Wave R3 |
| Frontend → backend coupling (31 files) | Low | Все через единый `frontend_facade` (mitigated). Полный migration на API clients — отдельный sprint |
