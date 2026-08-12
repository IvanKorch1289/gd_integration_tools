# Cycle 3 — Phase 1 — Domain: Services

> Аналитик домена `src/backend/services/**` + `tests/unit/services/**` за
> исключением поддоменов `ai/`, `workflow/`, `workflows/`, `security/`,
> `auth/`, `authorization/`, `agent_security/`.
>
> **Дата**: 2026-08-06 · **HEAD**: `7f3d94a388199c136bd7b90fa73d3b5a1217d4f7`
> · **Интерпретатор runtime-проверок**: `.venv/bin/python` (Python 3.14.0,
> `prometheus_client` ✅, `fastapi 0.141.1`, `hypothesis 6.165.1`,
> `jsonschema 4.26.0`).

---

## 1. Scope / что проверено / что не проверено

### 1.1. Scope (после исключений)

| Категория | Файлов исходников | Файлов тестов | LOC |
|---|---:|---:|---:|
| `services/admin/` | 6 | 2 | 244 + 86 + … |
| `services/audit/` (clickhouse_audit_service + workflow_audit_sink + unified_sink_factory + replay_query) | 6 | 7 | 716 + … |
| `services/billing/` | 2 | 1 | 38 + 177 |
| `services/cache/` | 3 | 1 | 165 + 25 + … |
| `services/codec/` | 1 | 0 | … |
| `services/capabilities/` | 1 | 0 | … |
| `services/core/` | 8 | 4 | … |
| `services/dsl/` | 2 | 1 | 165 + … |
| `services/dsl_portal/` | 1 | 0 | … |
| `services/execution/` (action_dispatcher + invoker + middlewares) | 8 | 6 | … |
| `services/integrations/` (rule_engine + express + skb + webhook_relay + facade + dadata + imported_action + import_service) | 11 | 3 | … |
| `services/io/` (dataframe + export_service + external_database + files + indexers + search + web_automation) | 13 | 2 | … |
| `services/jupyter/` | 12 | 4 | 1662 |
| `services/lineage/` | 2 | 2 | … |
| `services/messaging/` (facade + kafka_facade + outbox_monitor) | 3 | 0 | … |
| `services/notebooks/` | 4 | 0 | … |
| `services/notifications/` (apprise + facade) | 2 | 2 | … |
| `services/observability/` | 1 | 0 | 148 |
| `services/ops/` (analytics + anomaly_detector + data_quality + dq_remediation + health + message_replay + notification_adapters + notification_hub + notify_actions + scheduled_reports + webhook_scheduler) | 12 | 7 | … |
| `services/pii/` | 1 | 0 | 165 |
| `services/plugins/` (decorators + loader + registries + versioning + base_extensions) | 11 | 11 | … |
| `services/resilience/` | 2 | 2 | 247 + 5 |
| `services/routes/` (hot_reloader + loader + manifest_toml + route_authz) | 5 | 6 | … |
| `services/rpa/` (browser_cookies + browser_pool + desktop_rpa + desktop_session_pool + ocr_processor) | 5 | 4 | 1105 |
| `services/scheduler/` | 3 | 1 | … |
| `services/schema_registry/` | 6 | 4 | … |
| `services/secrets/` | 1 | 0 | … |
| `services/sources/` | 4 | 6 | … |
| `services/storage/` | 1 | 1 | … |
| `services/tenancy/` | 1 | 0 | 130 |
| `services/wiki/` | 1 | 1 | … |
| **Всего** | **~145** | **~85** | — |

### 1.2. Что верифицировано реально

- Все файлы под scope прочитаны (выборочно для крупных миксин-пакетов);
- `Grep` по `TODO/FIXME/XXX/HACK/raise NotImplementedError` во всём scope
  выполнен;
- Ключевые модули протестированы в `.venv/bin/python -m pytest`:
  - `tests/unit/services/audit/` — 47 passed, exit 0;
  - `tests/unit/services/ops/test_data_quality.py` +
    `test_dq_remediation.py` + `test_dq_extended.py` — 100 passed, exit 0;
  - `tests/unit/services/integrations/test_skb.py` — 10 passed, exit 0;
  - Полный целевой прогон остальных подразделов (см. §10) — 562 passed,
    1 skipped (polars — `tests/unit/services/core/test_tech.py:172`),
    1 deselected (`test_with_tenant_restores_previous` — отдельно зафиксирован
    как реальный fail, см. `DOMAIN-P0-001`).
- Runtime-проверки типов dataclass-дубликатов в data_quality выполнены:
  - `.venv/bin/python -c "from …apply_mixin import DQSeverity as S1; from
    …__init__ import DQSeverity as S0; print(S0 is S1)"` → `False`
    (см. §3, `DOMAIN-P1-001`).
- Прямой repro `TenantFacade.with_tenant()` через `.venv/bin/python -c
  …asyncio.run` → `TypeError: CapabilityTenant.__init__() got an
  unexpected keyword argument 'tenant_id'` (см. §3, `DOMAIN-P0-001`).
- Прямой repro `emit_admin_action` без wired callback → silent no-op
  (см. §3, `DOMAIN-P0-002`).

### 1.3. Что **не проверено**

- Полный код `services/jupyter/execution_service/e2b_backend.py`
  (326 LOC) — прочитал заголовок и публичные сигнатуры, но не внутренние
  методы (вне scope основных рисков).
- Полный код `services/plugins/loader/loading/*` — прочитал структуру,
  но не каждый mixin-метод.
- Конкретные lock-free гарантии `ServiceSchemaRegistry` в async — на
  практике не воспроизводил; оставил как «теоретический residual».
- DLQ-wiring `ClickHouseAuditService` в `core.di.composition` через grep
  показал отсутствие `set_dlq_writer` для audit singleton (см.
  `DOMAIN-P0-003`), но полный обход всех `composition/*.py` файлов не
  делал.
- `services/audit/workflow_audit_sink.py` — прочитал полностью, но
  проверка реального `_writer` инстанса вне scope.
- Производственные env-переменные `RESILIENCE_RATE_LIMIT_FAIL_MODE`,
  `JUPYTER_BACKEND` и т.п. — не воспроизводил, опирался на docstring/
  default-значения из кода.
- Любые cycle-1 / cycle-2 markdown-отчёты и `KNOWN_ISSUES.md` /
  `CLAUDE.md` / `PLAN.md` / `DEEP_AUDIT_REPORT.md` /
  `triage_allowlist_report.md` — **явно запрещено правилами цикла**;
  все находки выведены из текущего кода + baseline + runtime.

---

## 2. Verified strengths

Что реально работает и соответствует clean architecture / EIP /
DI / fail-closed.

### 2.1. Capability-checked facades (R174 umbrella)

Все современные facade-классы в scope следуют единому паттерну:

- Конструктор принимает опциональный `capability_check: Callable[[str,
  str, str | None], None]` и `plugin: str` для audit-tagging.
- При наличии checker'а — обязательная проверка через
  `self._assert(...)` перед каждой публичной операцией.
- При отсутствии — capability check skip (для unit-тестов и dev).
- Все исключения логируются как structured
  `log_audit_event_lite(_logger, severity=..., event=..., error=...)`,
  не как `print` / silent pass.

Проверено на:
`UnifiedCacheFacade` (`services/cache/facade.py:36-165`),
`NotificationsFacade` (`services/notifications/facade.py:42-251`),
`ResilienceFacade` (`services/resilience/facade.py:39-247`),
`ObservabilityFacade` (`services/observability/facade.py:40-148`).

### 2.2. Tiered cache fallback chain

`UnifiedCacheFacade.get/set/delete/exists` (`services/cache/facade.py:69-152`)
проходит **primary → memory → disk** в try/except на каждом уровне с
WARNING-логом, не падает на ошибках нижнего уровня (правильная
graceful-degradation семантика).

### 2.3. Idempotency с явным fail-mode

`RedisDedupeStore` (`services/sources/idempotency.py:72-127`) — явный
`fail_closed: bool = False` параметр; при `True` re-raises Redis-ошибку,
при `False` degrades to non-dup + WARNING. Docstring явно предписывает
prod-профилям override.

Тесты покрывают оба режима: `tests/unit/services/sources/test_redis_dedupe_fail_closed.py`.

### 2.4. Async-first + `asyncio.to_thread` для CPU-bound

`PytesseractOCRProcessor.recognize`
(`services/rpa/ocr_processor.py:90-116`) — sync `pytesseract.image_to_string`
обёрнут в `asyncio.to_thread`. Event-loop не блокируется. S164 W3 фикс
задокументирован.

### 2.5. EIP-pattern processors в data_quality (S55 W4 decomp)

`DataQualityMonitor` собирается из 4 mixin'ов
(`RuleManagementMixin, CheckMixin, SchemaMixin, ApplyMixin`)
через MRO. Каждый миксин имеет `__slots__ = ()` для предотвращения
shadowing атрибутов. Структурный контракт зафиксирован в
`_DataQualityProtocol` (`_protocol.py:20-41`).

### 2.6. Composition-root DI singleton pattern

`app_state_singleton("notification_hub", factory=NotificationHub)` и
аналогичные (`services/ops/anomaly_detector.py:148`,
`services/ops/message_replay.py:185`,
`services/ops/scheduled_reports.py:209`,
`services/ops/webhook_scheduler.py:169`,
`services/io/web_automation.py:128`,
`services/io/export_service.py:405`) — корректный lazy-resolve через
фабрику; функция содержит `raise NotImplementedError  # заменяется
декоратором` как placeholder, что безопасно (decorator перехватывает до
достижения `raise`).

### 2.7. Resilience patterns (circuit breaker + retry) — обёртки

`desktop_rpa_client.py:54-89` — общий circuit-breaker
`get_breaker_registry().get_or_create("desktop_rpa_client", BreakerSpec(...))`
+ retry через `make_async_retry`. Делегировано в
`core.resilience.retry` (уже tenacity-based, не custom loop).

### 2.8. Webhook Relay — Redis DLQ с fallback

`WebhookRelay._dlq_push/_dlq_all/_dlq_remove`
(`services/integrations/webhook_relay.py:262-318`) — Redis-first
(`LPUSH/LTRIM/LRANGE/LREM`), memory-fallback. Cap в `_DLQ_MAX_LEN =
10_000` предотвращает unbounded growth.

### 2.9. Schema-registry lock-free контракт

`ServiceSchemaRegistry` (`services/schema_registry/registry.py:87-283`)
— single-writer / many-reader модель: dict-replace atomic, `list_kind`
снимает snapshot ключей, `clear` атомарно переустанавливает
inner-dict. Docstring явно объясняет, почему RLock был заменён (deadlock
в async). `to_snapshot` / `from_snapshot` — versioned
`{"version": "2.0", "entries": [...]}`.

### 2.10. Audit-replay в services-слое (бывший reverse-layer)

`services/audit/replay_query.py` — канонический placement для
`list_audit_records` / `replay_audit_record`. Docstring (lines 1-16)
фиксирует, что это **бывший** reverse-layer (был в
`entrypoints/middlewares/audit_replay.py`), перенесён в services по
Ponytail D-rules. **RESIDUAL fixed (cycle 2)** — теперь не нарушает
architecture.

### 2.11. Reverse-layer shims (skb.py + files.py) — корректные

Оба shim-модуля — **forwarding-only** с явным `DeprecationWarning`:

- `src/backend/services/integrations/skb.py:142-151` — `resolve_waf_route`
  → `extensions.skb.services.waf_route.resolve_waf_route` с
  `warnings.warn(..., DeprecationWarning, stacklevel=2)`. Cycle-35 B2
  документирован.
- `src/backend/services/io/files.py:1-19` — `FileService,
  get_file_service` → `extensions.core_entities.files.services.files` с
  `warnings.warn(...)`. Sprint 7 R-V15-16 документирован.

Канонические модули **существуют** и **импортируются** в shim'ах —
forwarding работает (verified через `python -c "from
src.backend.services.io.files import get_file_service"`).

**Residual**: 3 caller's всё ещё импортируют из shim'ов вместо
канонического пути (см. `DOMAIN-P1-003`).

### 2.12. ClickHouse DLQ unification

`ClickHouseAuditService._send_to_dlq`
(`services/audit/clickhouse_audit_service/service.py:158-244`) — приоритет:

1. `self._dlq_writer` (canonical `DLQWriter` Protocol) → Inbox/Kafka/NATS;
2. `self._dlq_path` legacy → JSONL через `JsonlAuditBackend` (deprecated);
3. `None` → silent loss + WARNING.

Тесты покрывают оба приоритета и silent-loss:
`tests/unit/services/audit/test_clickhouse_audit_dlq.py` (8 тестов),
`test_clickhouse_audit_dlq_writer.py` (6 тестов, все priority-modes).

`fire-and-forget` семантика — DLQ-failure не пробрасывается caller'у
(observability не должна ломать hot-path). Задокументировано.

### 2.13. Workflow audit через bulk-writer (10x throughput)

`WorkflowAuditSink` (`services/audit/workflow_audit_sink.py`) —
делегирует в `ClickHouseBulkWriter` (не per-row insert). Composition
root wiring: `_init_workflow_audit_sink` создаёт writer + sink +
регистрирует singleton (`plugins/composition/setup_infra/workflow_audit.py:16-48`).
Lifespan-aware — `aclose()` делает flush.

### 2.14. PII-mask с audit-event

`PIIFacade.mask()` (`services/pii/facade.py:56-71`) — после успешного
masking эмитит audit-event `pii.masked` через
`log_audit_event_lite(payload_size=len(text))`. Не логирует сам PII
(только размер).

### 2.15. Billing fail-mode явный

`NoOpBillingFacade._ensure_disabled_or_raise` —
`if BILLING_ENABLED: raise NotImplementedError(...)`. **Fail-closed by
default**: feature-flag OFF → allowed=True + audit-event
`quota_check_skipped`; flag ON → жёсткий fail-closed через
`NotImplementedError`. Тесты покрывают оба режима
(`tests/unit/services/billing/test_no_op_billing_cycle33.py`).

### 2.16. NotificationsFacade — graceful degradation

`NotificationsFacade._send_via_messaging/_via_apprise`
(`services/notifications/facade.py:146-210`) — оба пути в
try/except с WARNING + return False. Не падает на partial-outage.

---

## 3. Findings (P0..P4)

### 3.1. Findings table

| ID | Priority | Path:Line | Evidence | Impact |
|---|---|---|---|---|
| `DOMAIN-P0-001` | P0 | `src/backend/services/tenancy/facade.py:116` | TypeError при runtime | `async with facade.with_tenant("tenant_42")` падает с `TypeError: CapabilityTenant.__init__() got an unexpected keyword argument 'tenant_id'`. **Все** DSL-процессоры и middlewares, использующие `TenantFacade.with_tenant()` для tenant-scoping, не работают. |
| `DOMAIN-P0-002` | P0 | `src/backend/services/admin/audit.py:60-62` + composition root отсутствует | audit_callback никогда не wired | `emit_admin_action` молча no-op (logger.debug). Admin действия (toggle_feature_flag, list_active_sessions, get_audit_log) не audit'ятся в production. Compliance gap. |
| `DOMAIN-P0-003` | P0 | `src/backend/services/audit/clickhouse_audit_service/service.py:222-223` + composition root | `set_dlq_writer` для audit singleton не вызывается | При сбое ClickHouse + без `dlq_path` → silent loss (priority 3). Audit-events теряются без персистенса. Нет `_dlq_writer_guard` в отличие от `cdc_client_adapter._dlq_writer_guard.py`. |
| `DOMAIN-P0-004` | P0 | `src/backend/services/pii/facade.py:67-71, 96-101` | fail-open на PII mask | `mask()` и `tokenize()` возвращают **исходный текст** при exception. Если masker упал — PII остаётся в возврате и попадает в logs / observability. **Fail-open на sensitive data**. |
| `DOMAIN-P0-005` | P0 | `src/backend/services/admin/api.py:97-102` | `_authorize` fail-open при AuthZ недоступен | Если `AuthorizationGateway` не резолвится → `_authorize` логирует WARNING и **позволяет действие**. Нарушение fail-closed policy из AGENTS.md. |
| `DOMAIN-P1-001` | P1 | `src/backend/services/ops/data_quality/{__init__.py, apply_mixin.py, check_mixin.py, schema_mixin.py, rule_mgmt_mixin.py}` (4 dataclass × 5 файлов) | dataclass-дубликаты | `DQSeverity`, `DQViolation`, `DQCheckResult`, `DQRule` объявлены в 5 файлах → `id()` разные → `isinstance(x, DQViolation)` совпадает только если импортировано из того же модуля. Verified через `.venv/bin/python -c "from apply_mixin import DQSeverity as S1; from __init__ import DQSeverity as S0; print(S0 is S1)"` → `False`. |
| `DOMAIN-P1-002` | P1 | `src/backend/services/ops/data_quality/check_mixin.py:80-160` vs `apply_mixin.py:370-401` | cross-mixin inconsistency в именах check + params | `_check_rule` ожидает `check="regex"` + `params["allowed"]`, а `_apply_rule` ожидает `check="regex_match"` + `params["values"]`. `check()` использует `_apply_rule`, `remediate()` использует `_check_rule` → если rule объявлен как `regex_match`/`values`, `remediate()` **не видит violation** (но тест `test_remediate_regex_mask` использует устаревший `regex`). |
| `DOMAIN-P1-003` | P1 | `src/backend/services/integrations/skb.py` + `src/backend/services/io/files.py` (shims) | 3 production callers всё ещё импортируют из shim'ов | `src/backend/plugins/composition/service_setup.py:202`, `src/backend/dsl/commands/setup/registers_domains.py:70`, `src/backend/entrypoints/api/v1/endpoints/files.py:20` — backward-compat работает, но shim-ы эмитят DeprecationWarning на каждый import. |
| `DOMAIN-P1-004` | P1 | `src/backend/services/scheduler/cron_dashboard_service.py:110-137` | `get_success_rate` возвращает `0.0` при client=None или query fail | Ambiguous: 0.0 означает либо «нет данных», либо «100% failure». Dashboard может показывать green при fully-broken ClickHouse. |
| `DOMAIN-P2-001` | P2 | `src/backend/services/admin/api.py:211-221, 232-244` | `get_audit_log` и `list_active_sessions` всегда возвращают `[]` | Задокументировано как «backend storage is TBD» и «session tracking TBD». Методы экспонированы через admin endpoint, вызывают audit-event, но возвращают мусор. Dead code с side-effect (audit-event). |
| `DOMAIN-P2-002` | P2 | `src/backend/services/billing/quotas_service.py:17-37` | Stub QuotasService | `__init__` бросает `NotImplementedError`; `consume_request` / `check_tokens` — тоже. Документировано, но не вызывается (используется `NoOpBillingFacade`). |
| `DOMAIN-P2-003` | P2 | `src/backend/services/audit/clickhouse_audit_service/service.py:222` | `# 3. None → silent loss + WARNING (как было до S36 P0 fix)` | Docstring описывает silent_loss как «как было до S36 P0 fix». Это residual исторического бага; нужно либо fail-closed по умолчанию (raise) либо обязательный dlq_writer. |
| `DOMAIN-P3-001` | P3 | `src/backend/services/ops/data_quality/apply_mixin.py:315-346` | `jsonschema` уже установлен (4.26.0) | Кастомная реализация `_apply_json_schema` может быть заменена на `Draft202012Validator.validate` (уже используется в `schema_registry/registry.py:266`). LOC delta ~ -25. |
| `DOMAIN-P3-002` | P3 | `src/backend/services/notifications/apprise_service.py` | `apprise` уже установлен | Используется корректно. **Нет кандидата** для замены. (negative finding) |
| `DOMAIN-P4-001` | P4 | `src/backend/services/ops/data_quality/*` | 8 новых check types | `regex_match`, `enum`, `length`, `date_format`, `cross_field`, `json_schema`, `cardinality` — Camel-style проверки. Уже имплементированы. **Нет нового feature для adding**. (negative finding) |
| `DOMAIN-P4-002` | P4 | `src/backend/services/jupyter/execution_service/*` | 4 backend kinds | `HUB`, `PAPERMILL`, `NBCLIENT`, `E2B` — Camel-стиль factory. **Нет кандидата**. (negative finding) |

### 3.2. Detailed evidence по каждому finding

#### DOMAIN-P0-001 — TenantFacade.with_tenant broken at runtime

**Path**: `src/backend/services/tenancy/facade.py:115-120`

**Evidence** (runtime repro):
```
.venv/bin/python -c "
from src.backend.services.tenancy.facade import TenantFacade
import asyncio
async def t():
    f = TenantFacade()
    async with f.with_tenant('tenant_42'):
        pass
asyncio.run(t())" → TypeError: CapabilityTenant.__init__() got an unexpected
keyword argument 'tenant_id'
```

Также failing test в CI:
`tests/unit/services/test_facades.py::TestTenantFacade::test_with_tenant_restores_previous`
→ exit 1 (выполняется с `.venv/bin/python -m pytest` — exit 1).

**Root cause**: `CapabilityTenant.__init__(id, principal, scope_glob)`
(`src/backend/core/security/capabilities/tenant.py:35-58`), но facade
передаёт `tenant_id=..., principal_id=...` (имена полей
`TenantContext`, а не `CapabilityTenant`). Docstring facade'а
(`services/tenancy/facade.py:97-110`) явно говорит «использует
``CapabilityTenant``», но kwargs неправильные.

**Impact**: Любой caller `async with TenantFacade().with_tenant(tenant_id,
principal_id)` падает с TypeError. Это ломает tenant-scoping во всех
DSL-процессорах и middlewares, которые используют facade (search через
`grep` показывает 0 прямых импортов `TenantFacade.with_tenant` в
in-scope коде — возможно, ещё не интегрирован в hot-path, но любой
будущий caller получит TypeError).

**Минимальная рекомендация**: исправить kwargs на `id=tenant_id,
principal=principal_id`. Также рассмотреть замену на `TenantContext` (как
заявлено в S183 I-4 docstring), если downstream использует
`ctx.tenant_id`/`ctx.principal_id`.

**Тест-критерий**:
`tests/unit/services/test_facades.py::TestTenantFacade::test_with_tenant_restores_previous`
→ exit 0; новый позитивный test на actual CapabilityTenant instance
creation через facade.

---

#### DOMAIN-P0-002 — admin audit_callback никогда не wired

**Path**: `src/backend/services/admin/audit.py:60-66` + composition root
отсутствует.

**Evidence** (grep):
```
$ grep -rn "set_audit_callback" src/backend/plugins/  --include="*.py"
(0 results)
```

То есть `set_audit_callback(...)` нигде в composition root не
вызывается → `_audit_callback` остаётся `None` → `emit_admin_action`
делает `logger.debug("audit_callback not set — skipping %s", ...)` и
return. Audit-event **не отправляется**.

Repro:
```
.venv/bin/python -c "
from src.backend.services.admin.audit import emit_admin_action
emit_admin_action(actor='t', action='x', resource='y', outcome='allowed')"
→ (no output, no exception)
```

**Impact**: Все admin actions (`toggle_feature_flag`, `get_audit_log`,
`list_active_sessions`) **не audit'ятся в production**. Compliance gap
(банковский продукт). Docstring в `services/admin/audit.py:24-28` явно
говорит «called by app bootstrap» — но app bootstrap не вызывает.

**Минимальная рекомендация**: в composition root (вероятно,
`plugins/composition/setup_infra/` или новый `admin_setup.py`) добавить
`set_audit_callback(...)` с реальной функцией, которая пишет в
ClickHouseAuditService или unified AuditService.

**Тест-критерий**:
`tests/unit/services/admin/test_audit_callback_wiring.py::test_admin_action_emits_to_audit`
— assert, что при выставленном callback реально emit'ится audit-event.

---

#### DOMAIN-P0-003 — ClickHouse audit silent_loss в production

**Path**: `src/backend/services/audit/clickhouse_audit_service/service.py:184-244`
+ composition root.

**Evidence** (grep):
```
$ grep -rn "audit.*set_dlq_writer\|set_dlq_writer.*audit\|get_audit_service" \
    src/backend/plugins/ --include="*.py"
(0 results — нет wiring set_dlq_writer для ClickHouseAuditService)
```

Сравнение — `cdc_client_adapter._dlq_writer_guard.py` (4 file, 1
function): для CDC есть guard, для audit — нет.

В `get_audit_service()` (`services/audit/clickhouse_audit_service/helpers.py:80-99`)
всегда создаётся `ClickHouseAuditService()` без `dlq_writer`. В
composition root (`plugins/composition/setup_infra/`) wiring
`workflow_audit_sink.set_workflow_audit_sink(sink)` есть, но **не**
`get_audit_service().set_dlq_writer(...)`.

Docstring (`services/audit/clickhouse_audit_service/service.py:46`)
фиксирует: «3. None → silent loss + WARNING (как было до S36 P0 fix)» —
то есть исторически было багом, сейчас задокументировано, но
composition root не закрыл.

**Impact**: При сбое ClickHouse в production + без legacy `dlq_path` →
audit-events теряются без персистенса (silent_loss path 3). Никаких
recover-механизмов нет (нет DLQ-replay-job, нет forensic).

**Минимальная рекомендация**: в composition root добавить
`audit_singleton.set_dlq_writer(inbox_dlq_writer)` (по аналогии с
CDC). Создать guard `_audit_dlq_writer_guard` (по аналогии с CDC).

**Тест-критерий**:
`tests/unit/services/audit/test_audit_dlq_writer_wired_in_composition.py::test_composition_root_wires_dlq_writer`
— assert, что `get_audit_service()._dlq_writer is not None` после
composition bootstrap.

---

#### DOMAIN-P0-004 — PII mask fail-open

**Path**: `src/backend/services/pii/facade.py:67-71, 96-101`.

**Evidence** (line 67-71):
```python
result = self.masker.mask_text(text)
self._emit_audit("pii.masked", text)
return result
except Exception as exc:
    _logger.warning("PII mask failed: %s", exc)
    return text   # ← возвращает ORIGINAL text при ошибке
```

Та же проблема в `tokenize()` (lines 96-101) и `mask_struct()`
(lines 82-86).

**Impact**: Если PII masker упал (например, regex-категория для INN не
зарегистрирована) — caller получает **исходный текст с PII**. Этот
текст может попасть в логи / structured logging / external storage.
Банковский продукт → GDPR / 152-ФЗ compliance.

Сравнение: `services/audit/clickhouse_audit_service/service.py:293-299`
при сбое ClickHouse emit'ит `_logger.warning` и **продолжает
DLQ-fallback** — это правильный fail-mode (audit-логирование
best-effort, но с fallback). Аналогично для observability, cache.

Для PII правильный fail-mode — **raise** (fail-closed), либо
возвращать явно-redacted marker (например, `"[PII_MASK_FAILED]"`), но
**не** original text.

**Минимальная рекомендация**: либо `raise PIIMaskError` из facade, либо
возвращать `"[MASK_FAILED]"` marker. Docstring должен явно описать
fail-mode.

**Тест-критерий**:
`tests/unit/services/test_facades.py::TestPIIFacade::test_mask_fails_closed_on_masker_error`
— assert, что `mask(...)` raises или возвращает marker, **не**
original.

---

#### DOMAIN-P0-005 — AdminService._authorize fail-open

**Path**: `src/backend/services/admin/api.py:96-103`.

**Evidence** (lines 96-103):
```python
authz = self._get_authz()
if authz is None:
    # AuthZ unavailable — fail-open for dev, but log warning
    logger.warning(
        "AuthZ unavailable for %s@%s/%s — allowing", actor, resource, action
    )
    return   # ← fail-OPEN: разрешает действие
```

**Impact**: Если `AuthorizationGateway` не резолвится (например,
composition root забыл wiring, или DI-контейнер сломан в prod) —
**все admin actions проходят без проверки прав**. Это нарушение
fail-closed policy из `AGENTS.md`: «fail-closed security».

Сравнение: `QuotaCheckMiddleware` (cycle 33 B-05) сделал rate-limit
fail-closed (deny-by-default) после того, как cycle 1 audit показал
fail-open. Аналогичный фикс нужен здесь.

**Минимальная рекомендация**: заменить `return` на
`raise AdminAuthorizationError("AuthZ unavailable; fail-closed")` —
или хотя бы `return` заменить на `raise`, чтобы caller упал громко.

**Тест-критерий**:
`tests/unit/services/admin/test_authorization_fail_closed.py::test_authorize_raises_when_authz_unavailable`.

---

#### DOMAIN-P1-001 — data_quality dataclasses 5-way duplication

**Path**:
- `src/backend/services/ops/data_quality/__init__.py:68-133`
- `src/backend/services/ops/data_quality/apply_mixin.py:30-71`
- `src/backend/services/ops/data_quality/check_mixin.py:28-69`
- `src/backend/services/ops/data_quality/schema_mixin.py:29-70`
- `src/backend/services/ops/data_quality/rule_mgmt_mixin.py:30-78`

**Evidence** (runtime):
```
.venv/bin/python -c "
from apply_mixin import DQSeverity as S1, DQViolation as V1
from check_mixin import DQSeverity as S2, DQViolation as V2
from schema_mixin import DQSeverity as S3, DQViolation as V3
from rule_mgmt_mixin import DQSeverity as S4, DQViolation as V4
from __init__ import DQSeverity as S0, DQViolation as V0
print(S0 is S1, S0 is S2, S0 is S3, S0 is S4)
print(V0 is V1, V0 is V2, V0 is V3, V0 is V4)
"
→ False False False False
→ False False False False
```

**Impact**:
- `isinstance(x, DQViolation)` совпадает **только если caller
  импортирует DQViolation из того же модуля, что и producer**.
- Mixins через MRO имеют `_seen_keys`, `_numeric_history`,
  `_cardinality_counts` как state — они работают через Protocol (см.
  `_DataQualityProtocol`), но если кто-то снаружи проверит
  `isinstance(monitor, DataQualityMonitor)` — это OK (один общий
  класс), а `isinstance(rule, DQRule)` — сломано (5 разных классов).
- Комментарий `apply_mixin.py:61`, `check_mixin.py:59`,
  `schema_mixin.py:60`, `rule_mgmt_mixin.py:68`:
  `# DQRemediationResult lives in __init__.py (S153 W1: 5x dedup)` —
  S153 W1 попытался сделать dedup, но перенёс только
  `DQRemediationResult`, оставив `DQSeverity/DQViolation/DQCheckResult/DQRule`
  дублированными в 5 местах.

**Минимальная рекомендация**: вынести 4 dataclass'а в
`src/backend/services/ops/data_quality/_types.py` и импортировать из
каждого mixin'а. Удалить локальные копии. Тесты уже покрывают
конкретные dataclass, но через разные пути импорта — нужно
добавить `isinstance`-test на dataclass из каждого модуля.

**Тест-критерий**:
`tests/unit/services/ops/test_data_quality.py::test_dataclass_identity_across_modules`
— assert, что `from apply_mixin import DQSeverity is from __init__
import DQSeverity`.

---

#### DOMAIN-P1-002 — data_quality check vs remediate inconsistency

**Path**:
- `src/backend/services/ops/data_quality/check_mixin.py:80-160` (`_check_rule`)
- `src/backend/services/ops/data_quality/apply_mixin.py:370-401` (`_apply_rule`)

**Evidence**:
| check type | `_apply_rule` (apply_mixin) | `_check_rule` (check_mixin) |
|---|---|---|
| regex | `"regex_match"` | `"regex"` |
| enum | `params["values"]` | `params["allowed"]` |
| type | `params["type"]` | `params["expected_type"]` |

`_apply_rule` используется в `check()` (`check_mixin.py:162-196`),
`_check_rule` используется в `remediate()`
(`rule_mgmt_mixin.py:150`).

Tests:
- `test_dq_extended.py:30, 44, 55` — `check="regex_match"` →
  проверяется через `check()` flow.
- `test_dq_remediation.py:325-329` — `check="regex"` → проверяется
  через `remediate()` flow.

Если rule объявлен как `check="regex_match"` + `params={"pattern":
"..."}`, то `remediate()` НЕ найдёт violation (потому что
`_check_rule` ждёт `check="regex"`).

**Impact**: `remediate()` пропустит нарушения, объявленные в
новом стиле (regex_match, values). `fixes_applied` будет undercount.

**Минимальная рекомендация**: либо унифицировать check-names и
param-keys в одном месте (constants), либо удалить
`_check_rule` совсем (он полностью дублирует логику из `_apply_*`
helpers в apply_mixin).

**Тест-критерий**:
`tests/unit/services/ops/test_data_quality.py::test_remediate_finds_violation_for_regex_match_rule`.

---

#### DOMAIN-P1-003 — 3 callers всё ещё импортируют из shim'ов

**Path**:
- `src/backend/plugins/composition/service_setup.py:202`
  → `from src.backend.services.io.files import get_file_service`
- `src/backend/dsl/commands/setup/registers_domains.py:70`
  → `from src.backend.services.io.files import get_file_service`
- `src/backend/entrypoints/api/v1/endpoints/files.py:20`
  → `from src.backend.services.io.files import get_file_service`

**Evidence**: `grep -rn "from src.backend.services.io.files" src/`
показывает 3 production callers; `extensions.core_entities.files.services.files`
есть (`extensions/core_entities/files/services/files.py`).

`skb.py` shim (resolve_waf_route) — grep показывает 0 прямых
imports из shim'а вне самого `services/integrations/skb.py` (canonical
import через `_waf_route()`). So skb.py shim — dead-code-only;
`files.py` shim — actively used.

**Impact**:
- `files.py` shim эмитит `DeprecationWarning` на каждый import →
  log spam в production.
- Cycle 1 deferred T-2.1 «reverse-layer cleanup» — residual.

**Минимальная рекомендация**: перевести 3 callers на canonical
`extensions.core_entities.files.services.files.get_file_service`.
Удалить `src/backend/services/io/files.py` после Sprint 37+ (как
заявлено в docstring).

**Тест-критерий**:
`tests/unit/services/io/test_files_shim_removal.py` —
после миграции assert, что `import src.backend.services.io.files`
raises `ModuleNotFoundError` или `ImportError`.

---

#### DOMAIN-P1-004 — CronDashboardService.get_success_rate ambiguous 0.0

**Path**: `src/backend/services/scheduler/cron_dashboard_service.py:110-137`.

**Evidence** (lines 110-115 + 124 + 131-132):
```python
client = await self._get_ch_client()
if client is None:
    return 0.0     # ← неотличимо от 100% failure
...
except Exception as exc:
    _logger.warning("CH success_rate failed: %s", exc)
    return 0.0     # ← неотличимо от 100% failure
```

**Impact**: Dashboard показывает 0% success rate как при fully-broken
ClickHouse, так и при отсутствии данных. Оператор не может
отличить «система работает, но нет данных» от «всё сломалось».

Сравнение: `services/scheduler/webhook_scheduler.py` возвращает
`{"status": "error", ...}` dict — explicit failure marker. Тот же
паттерн нужен здесь.

**Минимальная рекомендация**: возвращать `Optional[float]` + явный
marker (например, `(0.0, "no_data")` tuple или sentinel). Или
raise `ClickHouseUnavailableError`.

**Тест-критерий**:
`tests/unit/services/scheduler/test_cron_dashboard_service.py::test_success_rate_raises_on_client_unavailable`.

---

#### DOMAIN-P2-001 — admin get_audit_log / list_active_sessions return []

**Path**: `src/backend/services/admin/api.py:211-221, 232-244`.

**Evidence** (lines 211-213):
```python
# For now, return an empty list as backend storage is TBD.
# Frontend can call this endpoint; entries accumulate via callback.
```

`get_audit_log` (lines 199-221) и `list_active_sessions`
(lines 225-244) — оба всегда возвращают `[]`. Оба **проводят
AuthZ-проверку и эмитят audit-event**, но возвращают мусор.

**Impact**: Frontend admin pages получают пустые ответы → не
работают. Audit-events на эти обращения emit'ятся, но реальных
данных нет.

**Минимальная рекомендация**: либо реализовать backend storage
(unified AuditService уже есть), либо пометить endpoints как
not-implemented (501 Not Implemented).

**Тест-критерий**:
`tests/unit/services/admin/test_admin_endpoints.py::test_get_audit_log_returns_501_or_real_data`.

---

#### DOMAIN-P2-002 — QuotasService stub

**Path**: `src/backend/services/billing/quotas_service.py:17-37`.

**Evidence**: `__init__` бросает `NotImplementedError` (line 22-25).
Docstring явно говорит «Stub». Используется только как structural
type-marker для Protocol compatibility.

**Impact**: Dead code с side-effect на `import`. Не вызывается в
production (используется `NoOpBillingFacade`). Cycle 2 deferred.

**Минимальная рекомендация**: удалить модуль после Sprint 38 (или
пометить `# noqa: F401` если нужен для Protocol-typing).

**Тест-критерий**: нет (negative finding).

---

#### DOMAIN-P2-003 — DLQ silent_loss docstring как «pre-fix behavior»

**Path**: `src/backend/services/audit/clickhouse_audit_service/service.py:46`.

**Evidence**: `# 3. None → silent loss + WARNING (как было до S36 P0
fix)`.

**Impact**: Документированное поведение, но в production (при
отсутствии dlq_writer wiring, см. `DOMAIN-P0-003`) — это
fail-open audit. Docstring явно указывает на residual.

**Минимальная рекомендация**: см. `DOMAIN-P0-003` (composition
wiring).

**Тест-критерий**: см. `DOMAIN-P0-003`.

---

#### DOMAIN-P3-001 — jsonschema уже используется

**Path**: `src/backend/services/ops/data_quality/apply_mixin.py:315-346`,
`src/backend/services/schema_registry/registry.py:251-270`.

**Evidence**: `pyproject.toml` уже содержит `jsonschema` (verified:
`.venv/bin/python -c "import jsonschema; print(4.26.0)"` →
`jsonschema 4.26.0`). `schema_registry/registry.py:266` уже
использует `Draft202012Validator.check_schema` — канонический pattern.
`apply_mixin._apply_json_schema` (lines 315-346) делает то же самое
через `jsonschema.validate(instance, schema)`.

**Impact**: Code duplication; ~30 LOC можно удалить.

**Минимальная рекомендация**: заменить тело `_apply_json_schema` на
вызов общей helper-функции `validate_json_schema(value, schema)` из
`core.utils` или из `schema_registry`. License risk: jsonschema is
MIT, well-maintained (`python-jsonschema/jsonschema`).

**Тест-критерий**: existing test
`tests/unit/services/ops/test_dq_extended.py::test_json_schema_*`
(если есть) или новый test на helper reuse.

---

#### DOMAIN-P3-002 — apprise замены нет (negative)

**Path**: `src/backend/services/notifications/apprise_service.py`.

**Evidence**: `apprise` — зрелая multi-channel библиотека
(100+ backends), активно поддерживается. Уже используется корректно.

**Impact**: нет.

---

#### DOMAIN-P4-001 / DOMAIN-P4-002 — нет нового feature для adding (negative)

**Evidence**: В scope уже есть все Camel/Airflow-стиль primitive'ы:
- 8 check types в data_quality (regex_match, enum, length,
  date_format, cross_field, json_schema, cardinality, outlier +
  базовые not_null/type/range/unique).
- 4 jupyter backends (HUB, PAPERMILL, NBCLIENT, E2B).
- 4 DLQ-writer (kafka, rabbit, nats, inbox).
- 14+ protocol auto-registration (REST/SOAP/WSDL/gRPC/GraphQL/
  AsyncAPI/WS/SSE/MCP/MQTT/HTTP3/CDC/email/filewatcher/scheduler) —
  per AGENTS.md, but outside this scope.

`extensions/<name>/` — бизнес-логика per architecture rule. Никаких
новых feature для adding в scope `services/` не требуется.

---

## 4. Cycle-1 + Cycle-2 residuals (verified или mutated)

Поскольку cycle-1/cycle-2 markdown запрещено читать, residuals ниже
выведены из **baseline + текущего кода + моих runtime-проверок**.

| Source | ID | Статус | Evidence |
|---|---|---|---|
| Cycle 1 deferred | T-2.1 reverse-layer cleanup | RESIDUAL (verified) | Shim'ы существуют, но 3 callers ещё используют `files.py` shim (`DOMAIN-P1-003`). `services/audit/replay_query.py` уже перенесён из entrypoints (verified в §2.10). |
| Cycle 1 deferred | T-1.3 MQ DLQ data-loss | NOT IN SCOPE | Out of scope (`src/backend/services/audit/clickhouse_audit_service/service.py:158-244` имеет аналогичную проблему, см. `DOMAIN-P0-003`). |
| Cycle 1 deferred | T-1.1 composition root fix | NOT IN SCOPE | Out of scope (composition root). |
| Cycle 1 deferred | T-1.2 SSE/HITL auth | NOT IN SCOPE | Out of scope (entrypoints, auth). |
| Cycle 1 deferred | T-4.1 text-RAG E2E | NOT IN SCOPE | Out of scope (ai/). |
| Cycle 2 deferred | T-W1-02 CDC DLQ handoff | NOT IN SCOPE | Out of scope (infrastructure/cdc). |
| Cycle 2 deferred | T-W1-03 MQ subscribers ACK | NOT IN SCOPE | Out of scope (messaging). |
| Cycle 2 deferred | T-W1-04 composition root DI | RELATED | `DOMAIN-P0-003` — composition root не wire'ит `set_dlq_writer` для audit singleton (та же категория проблемы). |
| Cycle 2 deferred | T-W1-06 RagCachePrewarmer | NOT IN SCOPE | Out of scope (ai/). |
| Cycle 2 deferred | T-W1-07 SSE principal/permissions | NOT IN SCOPE | Out of scope (entrypoints). |
| Cycle 2 deferred | T-W2-01..04 layer track | PARTIAL | `services/audit/replay_query.py` перенесён из entrypoints (cycle 1 fix); `services/integrations/skb.py` shim корректен (`DOMAIN-P1-003` residual — shim есть, но 3 callers). |
| Cycle 2 deferred | T-W3-01 tenacity library replacement | NOT IN SCOPE | Out of scope (core/resilience). `services/rpa/desktop_rpa_client.py:76` уже использует `make_async_retry` из core (verified). |
| Cycle 2 deferred | T-W4-01 text-RAG E2E | NOT IN SCOPE | Out of scope (ai/). |
| Pre-existing | `services/ai/gateway_adapter.py:128-129` `except Exception: pass` | NOT IN SCOPE | Out of scope (ai/). |
| Pre-existing | uv.lock -15 svcs | PRE-EXISTING | Not in this plan. |
| Pre-existing | `.blue_green.state` | PRE-EXISTING | Not in this plan. |
| Pre-existing | `pip-audit.json` | PRE-EXISTING | Not in this plan. |
| Pre-existing | cycle-1 uncommitted правки (5 source + 4 test + 1 preflight) | NOT ATTRIBUTED | Cycle 3 не должен их ровнить — developer commit step. |
| Pre-existing | cycle-2 uncommitted правки (4 source + 2 test + 1 audit doc) | NOT ATTRIBUTED | Cycle 3 не должен их ровнить — developer commit step. |

**Цикл-1 фиксы, подтверждённые в текущем коде** (без чтения cycle-1 markdown, только по комментариям в коде):
- `services/audit/clickhouse_audit_service/helpers.py:17-19` —
  module-level singleton добавлен в S114 W1 (комментарий).
- `services/audit/clickhouse_audit_service/service.py:6-9` —
  S180 P1-#1 (DLQ unification через DLQWriter Protocol) — реализовано
  (verified, см. §2.12).
- `services/billing/no_op_billing.py:1-19` — cycle 33 B-07 fix
  (stub → no-op BillingFacade с audit event) — реализовано
  (verified).

---

## 5. Contradictions / overlaps для flagging

### 5.1. Dataclass duplication × mixin MRO — type-incompatibility risk

`DQSeverity/DQViolation/DQCheckResult/DQRule` объявлены в 5 файлах
(`__init__.py` + 4 mixin'а). Mixins через MRO в `DataQualityMonitor`
видят только **один** `DQViolation` (тот, что импортирован в
`__init__.py` — последний в MRO chain wins). Но если extension
импортирует `DQViolation` из `apply_mixin.py` напрямую, его
`isinstance(v, DQViolation)` не совпадёт с тем, что вернёт
`monitor.check()` (который использует apply_mixin, но Python смотрит
на class identity через MRO).

Это **latent type-incompatibility bug**, не срабатывающий в текущих
тестах (потому что все тесты импортируют из `__init__.py`).

### 5.2. Check-name divergence × remediation flow

См. `DOMAIN-P1-002`. Тест `test_remediate_regex_mask` использует
`check="regex"` (legacy), а `test_regex_match_passes/fails` —
`check="regex_match"` (новый). Если кто-то напишет rule с
`check="regex_match"` и вызовет `monitor.remediate(...)`,
`fixes_applied` будет 0 (violations не найдены).

### 5.3. PII-fail-open vs PII-compliance

`DOMAIN-P0-004` — fail-open для PII прямо противоречит compliance
(152-ФЗ, GDPR Art. 32 — security of processing). В банковском
продукте это допустимо только при наличии compensating controls
(например, downstream storage всегда маскирует PII). Никаких
evidence такого контроля в `services/pii/facade.py` нет.

### 5.4. AdminService fail-open vs AGENTS.md fail-closed

`DOMAIN-P0-005` — `_authorize` fail-open при AuthZ unavailable.
Прямо противоречит `AGENTS.md`: «fail-closed security». Это legacy
pre-Sprint 36 поведение, не закрытое в M-series audit.

### 5.5. shim-ы — backward-compat warning spam

`DOMAIN-P1-003` — 3 production callers импортируют из
`src/backend/services.io.files`. На каждый import эмитится
DeprecationWarning → log spam. Не критично, но noisy.

### 5.6. ClickHouseAuditService DLQ priority 3 — documented silent_loss

`DOMAIN-P0-003` + `DOMAIN-P2-003` — silent_loss path 3
задокументирован, но в production composition root не wire'ит
`dlq_writer`. Это означает, что в production audit-events
**фактически** теряются без персистенса.

---

## 6. Readiness score 0–100

### 6.1. Формула

```
score = 100
  - 15 × (count of P0)
  -  8 × (count of P1)
  -  3 × (count of P2)
  -  1 × (count of P3)
  -  0 × (count of P4)
```

(Коэффициенты подобраны эмпирически: P0 — критично для security /
data-loss / fail-open; P1 — architecture boundary / production-impact
correctness; P2 — dead code / TBD; P3 — minor cleanup; P4 —
out-of-scope new feature.)

### 6.2. Подсчёт

| Priority | Кол-во | Штраф |
|---|---:|---:|
| P0 | 5 | 75 |
| P1 | 4 | 32 |
| P2 | 3 | 9 |
| P3 | 2 (1 negative) | 1 |
| P4 | 2 (negative) | 0 |
| **Σ** | **14 (effective: 11)** | **117** |

### 6.3. Cap правило

> «Оценка ≥80 запрещена при наличии P0/P1.»

В scope обнаружено **5 P0** (`DOMAIN-P0-001..005`) и **4 P1**. По
правилу readiness score **≤ 79** (cap = 80 - 1 = 79 max).

### 6.4. Итог

```
score = max(0, 100 - 117) = 0
cap   = 79 (due to P0/P1 presence)
final = min(0, 79)        = 0
```

Но raw score отрицательный — это означает «категорически не ready».
Более информативная метрика:

```
readiness = 0 (raw) → 0 (capped) → 0 / 100
```

**Justification**: 5 P0 finding'ов — каждый из них блокирует
безопасный production rollout:
- `P0-001` ломает tenant-scoping runtime;
- `P0-002` ломает admin audit-trail (compliance);
- `P0-003` ломает audit-DLQ в production (data-loss);
- `P0-004` ломает PII-masking fail-closed (compliance);
- `P0-005` ломает admin AuthZ fail-closed (security).

**Рекомендуемая readiness score**: **0 / 100** (raw и capped).

---

## 7. Recommended next tasks

Все — для developer (не Phase 1 аналитика).

| ID | Priority | Effort | Что делать |
|---|---|---|---|
| `FIX-DOMAIN-P0-001` | P0 | S | `services/tenancy/facade.py:116` — заменить kwargs `tenant_id=` / `principal_id=` на `id=` / `principal=` (или использовать `TenantContext`). |
| `FIX-DOMAIN-P0-002` | P0 | M | Добавить `set_audit_callback` в `plugins/composition/setup_infra/` (или новый `admin_setup.py`), wire'ить на unified `AuditService.emit`. |
| `FIX-DOMAIN-P0-003` | P0 | M | В `plugins/composition/setup_infra/di.py` (или рядом) добавить `audit_singleton.set_dlq_writer(inbox_dlq_writer)` по аналогии с `cdc.set_dlq_writer(...)`. Создать `_audit_dlq_writer_guard.py` по аналогии с CDC. |
| `FIX-DOMAIN-P0-004` | P0 | S | `services/pii/facade.py:67-71, 96-101` — изменить fail-mode с return-original на `raise PIIMaskError` (или возврат marker). |
| `FIX-DOMAIN-P0-005` | P0 | XS | `services/admin/api.py:96-103` — заменить `return` на `raise AdminAuthorizationError("AuthZ unavailable; fail-closed")`. |
| `FIX-DOMAIN-P1-001` | P1 | M | Вынести 4 dataclass'а в `src/backend/services/ops/data_quality/_types.py`. Удалить из 4 mixin'ов. Обновить Protocol import. |
| `FIX-DOMAIN-P1-002` | P1 | M | Унифицировать check-names в `_check_rule` ↔ `_apply_rule`. Либо удалить `_check_rule` совсем (он дублирует apply-логику). |
| `FIX-DOMAIN-P1-003` | P1 | S | 3 callers: `plugins/composition/service_setup.py:202`, `dsl/commands/setup/registers_domains.py:70`, `entrypoints/api/v1/endpoints/files.py:20` — заменить на canonical `from extensions.core_entities.files.services.files import get_file_service`. После Sprint 37 — удалить `services/io/files.py`. |
| `FIX-DOMAIN-P1-004` | P1 | XS | `services/scheduler/cron_dashboard_service.py:110-137` — возвращать `Optional[float]` или tuple `(0.0, "no_data")` для explicit error semantic. |
| `FIX-DOMAIN-P2-001` | P2 | M | Реализовать `get_audit_log` через `AuditService.list_events` и `list_active_sessions` через session-tracking backend (или 501 Not Implemented). |
| `FIX-DOMAIN-P2-002` | P2 | XS | Удалить `services/billing/quotas_service.py` (dead code) или `# pragma: no cover` + comment. |
| `FIX-DOMAIN-P2-003` | P2 | S | Связан с `FIX-DOMAIN-P0-003`. После fix — изменить docstring (убрать «как было до S36 P0 fix»). |
| `FIX-DOMAIN-P3-001` | P3 | S | `services/ops/data_quality/apply_mixin.py:315-346` — вынести `validate_json_schema(value, schema)` в `core/utils` (или `schema_registry`), переиспользовать. |

---

## 8. Commands run

| # | Команда | Exit | Назначение |
|---|---|---|---|
| 1 | `.venv/bin/python -c "import prometheus_client, fastapi, hypothesis; print('OK')"` | 0 | Verify venv packages. |
| 2 | `git rev-parse HEAD` | 0 | Verify HEAD = `7f3d94a388199c136bd7b90fa73d3b5a1217d4f7`. |
| 3 | `find src/backend/services -name "*.py" \| grep -v -E "/(ai\|workflow\|workflows\|security\|auth\|authorization\|agent_security)/" \| wc -l` | 0 | Count in-scope service files (~145). |
| 4 | `grep -rn "TODO\|FIXME\|XXX\|HACK\|raise NotImplementedError" src/backend/services --include="*.py"` | 0 | Sweep для stubs/TODO. |
| 5 | `grep -rn "TODO\|FIXME\|XXX\|HACK" src/backend/services/audit --include="*.py"` | 0 | audit-specific. |
| 6 | `.venv/bin/python -m pytest tests/unit/services/audit/test_clickhouse_audit_dlq.py tests/unit/services/audit/test_clickhouse_audit_dlq_writer.py -v` | 0 | 14 passed (DLQ priority 1/2/3 tests). |
| 7 | `.venv/bin/python -m pytest tests/unit/services/audit/ -q` | 0 | 47 passed. |
| 8 | `.venv/bin/python -m pytest tests/unit/services/ops/test_data_quality.py tests/unit/services/ops/test_dq_remediation.py tests/unit/services/ops/test_dq_extended.py -q` | 0 | 100 passed. |
| 9 | `.venv/bin/python -m pytest tests/unit/services/integrations/test_skb.py -q` | 0 | 10 passed. |
| 10 | `.venv/bin/python -m pytest tests/unit/services/audit tests/unit/services/billing tests/unit/services/cache tests/unit/services/core tests/unit/services/dsl tests/unit/services/execution tests/unit/services/integrations tests/unit/services/lineage tests/unit/services/notifications tests/unit/services/ops tests/unit/services/resilience tests/unit/services/scheduler tests/unit/services/schema_registry tests/unit/services/sources tests/unit/services/storage tests/unit/services/wiki tests/unit/services/test_contract_adapter_fixes.py tests/unit/services/test_facades.py tests/unit/services/test_remaining_contract_adapters.py tests/unit/services/test_rule_engine_registry.py -q` | 0 | 562 passed, 1 skipped (polars), 1 deselected. |
| 11 | `.venv/bin/python -m pytest tests/unit/services/test_facades.py::TestTenantFacade::test_with_tenant_restores_previous --tb=long` | 1 | **FAILS** — TypeError. `DOMAIN-P0-001` confirmed. |
| 12 | `.venv/bin/python -c "from src.backend.services.ops.data_quality.apply_mixin import DQSeverity as S1; from src.backend.services.ops.data_quality import DQSeverity as S0; print(S0 is S1)"` | 0 | Outputs `False`. `DOMAIN-P1-001` confirmed. |
| 13 | `.venv/bin/python -c "from src.backend.services.tenancy.facade import TenantFacade; import asyncio; async def t(): f=TenantFacade(); async with f.with_tenant('t'): pass; asyncio.run(t())"` | 1 | **TypeError**. `DOMAIN-P0-001` runtime confirmed. |
| 14 | `.venv/bin/python -c "from src.backend.services.admin.audit import emit_admin_action; emit_admin_action(actor='t', action='x', resource='y', outcome='allowed')"` | 0 | Silent no-op. `DOMAIN-P0-002` confirmed. |
| 15 | `grep -rn "set_audit_callback" src/backend/plugins/ --include="*.py"` | 0 | 0 matches → wiring отсутствует. `DOMAIN-P0-002` root cause. |
| 16 | `grep -rn "audit.*set_dlq_writer\|get_audit_service" src/backend/plugins/ --include="*.py"` | 0 | 0 matches для set_dlq_writer на audit. `DOMAIN-P0-003` confirmed. |
| 17 | `grep -rn "from src.backend.services.io.files" src/ --include="*.py"` | 0 | 3 callers. `DOMAIN-P1-003` confirmed. |
| 18 | `.venv/bin/python -c "import jsonschema; print(jsonschema.__version__)"` | 0 | `4.26.0` → уже установлен. `DOMAIN-P3-001` confirmed. |
| 19 | `.venv/bin/python -m pytest tests/unit/services/cache tests/unit/services/notifications tests/unit/services/lineage -q` | 0 | 50 passed. |
| 20 | `.venv/bin/python -m pytest tests/unit/services/execution tests/unit/services/scheduler tests/unit/services/schema_registry tests/unit/services/wiki tests/unit/services/storage tests/unit/services/resilience tests/unit/services/integrations -q` | 0 | 165 passed. |
| 21 | `.venv/bin/python -m pytest tests/unit/services/dsl tests/unit/services/core tests/unit/services/billing tests/unit/services/sources -q` | 0 | 118 passed, 1 skipped. |
| 22 | `.venv/bin/python -m pytest tests/unit/services/io -q` | 0 | 12 passed. |
| 23 | `.venv/bin/python -m pytest tests/unit/services/jupyter -q` | 0 | 55 passed. |
| 24 | `.venv/bin/python -m pytest tests/unit/services/routes -q` | 0 | 78 passed, 9 skipped. |
| 25 | `.venv/bin/python -m pytest tests/unit/services/plugins -q` | 0 | 137 passed, 8 skipped, 1 xfailed. |
| 26 | `.venv/bin/python -m pytest tests/unit/services/admin -q` | 0 | 5 passed. |

**Интерпретатор всех runtime-проверок**: `.venv/bin/python` (Python 3.14.0).
**Использование system Python (как reviewer cycle 2) — запрещено** (правилами
cycle 3 baseline): system Python не имеет `prometheus_client` / `fastapi` /
`hypothesis` / `jsonschema`.

---

## 9. Notes for reviewer

1. **5 P0** finding'ов в scope — readiness score **0** (capped by rule
   «≥80 запрещена при P0/P1»).
2. `DOMAIN-P0-001` (TenantFacade TypeError) — **воспроизводится в
   однострочнике**, не требует полного bootstrap.
3. `DOMAIN-P0-002` (admin audit_callback) и `DOMAIN-P0-003` (audit DLQ
   wiring) — **composition-root gaps**, требуют fixes в
   `src/backend/plugins/composition/setup_infra/`.
4. `DOMAIN-P0-004` и `DOMAIN-P0-005` — **fail-open** на sensitive
   data и security, непосредственно противоречат AGENTS.md.
5. `DOMAIN-P1-001` (dataclass 5-way duplication) — **verified через
   `is`** (id mismatch), не теоретический.
6. `DOMAIN-P1-002` (check-name divergence) — **latent**, не
   срабатывает в текущих тестах (legacy `regex` используется в
   remediation tests, new `regex_match` — в check tests).
7. Pre-existing residuals (uv.lock -15, blue_green, pip-audit.json,
   cycle-1/cycle-2 uncommitted) — **НЕ** этому плану, явно
   зафиксировано в baseline.
8. Cycle-1/cycle-2 markdown отчёты **НЕ читал** по правилам цикла.
   Residuals в §4 выведены из baseline + текущего кода + runtime.
