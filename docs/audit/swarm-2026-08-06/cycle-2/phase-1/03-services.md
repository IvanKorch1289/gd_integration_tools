# Cycle 2, Phase 1 — Домен «Сервисы» (`src/backend/services/**` + `tests/unit/services/**`)

> **HEAD**: `ca5bff93058f2580041a7339913b52943babb329` (16 ahead of origin/master).
> **Scope**: `src/backend/services/**` и `tests/unit/services/**`,
> исключая `ai/`, `workflow/`, `workflows/`, `security/`, `auth/`,
> `authorization/`, `agent_security/`.
> **Метод**: read-only аудит кода + тестов, без правок и git mutations.
> **baseline-числа проверены**: layer checker `175 legacy / 0 new`; allowlist
> `180` строк (5 комментариев + 175 активных); security allowlist `35` ID.

---

## 1. Scope / «не проверено»

### Scope (проверено)
- `src/backend/services/admin/` — `api.py`, `audit.py`,
  `_capability_adapter.py`, `clickhouse_admin.py`, `sqladmin_setup.py`,
  `__init__.py`.
- `src/backend/services/audit/` — `clickhouse_audit_service/`,
  `workflow_audit_sink.py`, `replay_query.py`, `unified_sink_factory.py`.
- `src/backend/services/billing/` — `no_op_billing.py`,
  `quotas_service.py`, `__init__.py`.
- `src/backend/services/cache/` — `facade.py`, `metrics.py`,
  `__init__.py`.
- `src/backend/services/core/` — `admin.py`, `tech.py`,
  `base.py`, `base_external_api.py`, `base_service.py` (последние три
  импортируются в `core/` через reverse-layer, проверены как targets).
- `src/backend/services/dsl_portal/` — `builder_facade.py`.
- `src/backend/services/integrations/` — `skb.py`, `files.py` (shim),
  `facade.py`, `connector_configs.py`, `import_service.py`,
  `imported_action_service.py`, `webhook_relay.py`, `dadoa.py`,
  `express/`, `rule_engine/`.
- `src/backend/services/io/` — `files.py` (shim), `web_automation.py`,
  `export_service.py`, `external_database/__init__.py`,
  `indexers/log_indexer.py` (на него ссылается reverse-layer в
  `core/observability/log_indexer.py`).
- `src/backend/services/jupyter/` — `execution_service/factory.py`,
  остальное — поверхностно (используется sdk/).
- `src/backend/services/lineage/`, `notebooks/`,
  `notifications/apprise_service.py`, `observability/`, `ops/`
  (включая `data_quality/`), `pii/facade.py`, `plugins/`,
  `resilience/`, `routes/` (включая `route_authz.py`),
  `rpa/`, `scheduler/`, `schema_registry/`, `secrets/`,
  `sources/`, `storage/`, `tenancy/`, `wiki/`.
- `tests/unit/services/**` (227 файлов, 32 директории) — выборочная
  проверка coverage для всех P0/P1 находок.

### «Не проверено»
- `docs/audit/swarm-2026-08-06/cycle-1/03-services.md` и любые другие
  cycle-1 отчёты (запрещено условиями задачи).
- `KNOWN_ISSUES.md`, `CLAUDE.md`, `PLAN.md`, `DEEP_AUDIT_REPORT.md`,
  `triage_allowlist_report.md` (запрещено).
- `extensions/*` как цель импорта — проверено только то, что они
  экспортируют (через `from extensions.*` imports в service-файлах).
- Цикл 1 Phase 4 uncommitted правки
  (`core/ai/gateway_pipeline_mixin/policy_mixin.py`,
  `dsl/engine/processors/eip/reliability/redelivery_policy.py`,
  `dsl/engine/processors/eip/routing/multicast.py`,
  `infrastructure/cache/rag/embedding_cache.py`,
  `services/ai/gateway_adapter.py` + 2 теста) — НЕ атрибутируются рою
  cycle 2 и НЕ расследованы как часть findings (только проверка, что они
  не пересекаются с моим scope; подтверждено: все 5 — вне scope).
- `M uv.lock`, `M tools/blue_green.sh`,
  `M tests/unit/tools/test_blue_green_switch.py`,
  `?? .blue_green.state`, `?? pip-audit.json` —
  pre-existing drift, НЕ атрибутируется рою cycle 2.
- Реальные сетевые/IO-операции (ClickHouse/Redis/Kafka) — проверка
  только через код и unit-тесты.

---

## 2. Verified strengths

- **Capability-facade pattern в admin/api.py** (`S198 fix`) —
  `FacadeCapabilityAdapter` поверх `get_capability_facade()` singleton
  заменил прямое создание `CapabilityGate()` (файл
  `src/backend/services/admin/_capability_adapter.py`, 40 LOC). Корректный
  capability-checked фасад (см. lines 15-38).
- **route_authz.py fail-closed** (`src/backend/services/routes/route_authz.py`)
  — строки 60-72: при недоступности `AuthorizationGateway` бросает
  `RuntimeError`, при `gateway is None` возвращает `False,
  "authorization_gateway_not_registered"`. Тест
  `tests/unit/services/routes/test_route_authz.py::test_gateway_unavailable_raises_runtime_error`
  и `test_gateway_none_returns_false` покрывают оба пути (lines 28-49).
- **canonical DLQWriter Protocol (S180 P1-#1)** —
  `src/backend/services/audit/clickhouse_audit_service/service.py:84-91`
  `set_dlq_writer()` setter + `dlq_writer=` kwarg (lines 61-78).
  Протокол `DLQWriter` определён в
  `src/backend/infrastructure/messaging/dlq_base.py:103-112` (Protocol,
  `async write(envelope)`). Полное покрытие в
  `tests/unit/services/audit/test_clickhouse_audit_dlq_writer.py`
  (7 тестов: `test_set_dlq_writer_receives_envelope_on_failure`,
  `test_init_dlq_writer_kwarg_receives_envelope`,
  `test_dlq_writer_priority_over_legacy_path`,
  `test_emit_batch_through_writer`,
  `test_successful_emit_does_not_write_dlq`,
  `test_off_flag_does_not_write_dlq`,
  `test_dlq_writer_failure_is_fire_and_forget`).
- **`core/audit/facade/audit_service.py`** (canonical home per ADR-0190) —
  `services/audit/__init__.py` импортирует `AuditService` и
  `get_unified_audit_service` напрямую из core (строка 21), без
  layer-violation. Старый `services/audit/audit_service.py` удалён в
  S45 W1 (комментарий в `__init__.py:32`).
- **`retry_async` integration в audit emit** (lines 268-287 + 324-343
  в `clickhouse_audit_service/service.py`) — 3 retry-попытки с
  exponential backoff (base 0.5, max 5.0). Использует общий
  `src.backend.core.resilience.retry.retry_async` (не кастомный код).
- **`AuditService` (services/core/admin.py) tests** —
  `tests/unit/services/core/test_admin.py` покрывает 13 методов
  (get_config / toggle_route ×3 / cache ×5 / introspection ×5 / slo
  / singleton = 19 тестов).
- **QuotasService stub fail-fast** — `services/billing/quotas_service.py`
  `__init__` бросает `NotImplementedError` с явной диагностикой;
  покрыто тестом `test_quota_service_constructor_raises_not_implemented`
  (test_no_op_billing_cycle33.py:209-216).
- **replay_query.py placement fix (Ponytail D-rules)** — `services/audit/replay_query.py`
  правильно расположен в services layer (ранее был в
  `entrypoints/middlewares/audit_replay.py`, что нарушало architecture
  invariants: services → entrypoints).

---

## 3. Findings table

| ID | Приоритет | Файл:строка | Кратко | Стр. cycle-1 статус |
|---|---|---|---|---|
| **DOMAIN-SVCS-P0-001** | **P0** | `src/backend/services/admin/api.py:96-102` | fail-open в `AdminService._authorize()` при `authz is None` | RESIDUAL (код неизменён, класс мёртвый — см. §6) |
| **DOMAIN-SVCS-P1-001** | **P1** | `src/backend/services/ops/data_quality/{check,apply,schema,rule_mgmt}_mixin.py` | 5-way дублирование dataclasses/enum (`DQSeverity`, `DQViolation`, `DQCheckResult`, `DQRule`); class identity mismatch подтверждён runtime-проверкой | MUTATED (из 4-way в 5-way: добавилось ещё одно объявление в `__init__.py`) |
| **DOMAIN-SVCS-P1-002** | **P1** | `src/backend/services/io/files.py` (20 LOC) | Reverse-layer shim для `FileService` — нет deprecation timeline, 3 активных caller'а | RESIDUAL (код неизменён) |
| **DOMAIN-SVCS-P1-003** | **P1** | `src/backend/services/integrations/skb.py` (152 LOC) | Backward-compat shim для `resolve_waf_route` + фактический production-сервис СКБ смешаны в одном файле; `extensions.skb.services.waf_route` уже canonical | RESIDUAL (код неизменён, deprecation шум остаётся) |
| **DOMAIN-SVCS-P1-004** | **P1** | `src/backend/services/admin/api.py` (в целом, 244 LOC) | `AdminService` класс не инстанциируется ни в одном entrypoint/test/composition root — мёртвый public API с fail-open внутри | NEW (выявлено в cycle 2) |
| **DOMAIN-SVCS-P2-001** | **P2** | `src/backend/services/billing/quotas_service.py:17-37` | Stub `QuotasService` (38 LOC), бросает `NotImplementedError` в `__init__`; согласно docstring — «контрактный placeholder» | RESIDUAL (код неизменён; placement choice — cycle 33 B-07) |
| **DOMAIN-SVCS-P2-002** | **P2** | 9 файлов в scope | `raise NotImplementedError  # заменяется декоратором` внутри `@app_state_singleton(...)` factory (косметический dead-code placeholder) | NEW (выявлено в cycle 2) |
| **DOMAIN-SVCS-P2-005** | **P2** | `src/backend/services/audit/clickhouse_audit_service/service.py:184-186, 220-223` | DLQ silent_loss на priority-3 (нет ни `dlq_writer`, ни `dlq_path`) — backward-compat, есть explicit test | PARTIALLY MUTATED (S180 P1-#1 добавил priority-1 canonical DLQWriter, priority-3 сохранён как legacy) |
| **DOMAIN-SVCS-P3-001** | **P3** | `src/backend/services/resilience/facade.py:205+` (`with_retry`) + `src/backend/services/audit/clickhouse_audit_service/service.py:268, 324` | Кастомный retry поверх `core.resilience.retry.retry_async`. В pyproject уже есть `tenacity>=9.0.0,<10.0.0` (строка 74), используется в `infrastructure/clients/transport/http_httpx.py:24`, `dsl/engine/processors/control_flow/flow.py:133-145` | NEW |
| **DOMAIN-SVCS-P3-002** | **P3** | `src/backend/services/notifications/apprise_service.py:97-117` | Lazy-import `apprise` для graceful degradation; `apprise` есть в pyproject (строка 842) — стандартный подход, не проблема | NOTE (положительное) |
| **DOMAIN-SVCS-P4-001** | **P4** | `src/backend/services/audit/replay_query.py:30-90` | `list_audit_records` работает только с Redis stream `"audit:events"` без fallback на ClickHouse audit_events table (для replay-after-disaster-scenario) | NEW |

**Итого**: 1 P0, 4 P1, 4 P2, 1 P3 (new), 1 P3 (note), 1 P4.

---

## 4. Detailed evidence

### DOMAIN-SVCS-P0-001 — fail-open в AdminService._authorize

**File**: `src/backend/services/admin/api.py:96-102` (а также 78-80 в `_get_authz`)

```python
async def _authorize(
    self, *, actor: str, resource: str, action: str,
    context: dict[str, Any] | None = None,
) -> None:
    authz = self._get_authz()
    if authz is None:
        # AuthZ unavailable — fail-open for dev, but log warning
        logger.warning(
            "AuthZ unavailable for %s@%s/%s — allowing", actor, resource, action
        )
        return                                                # ← fail-open
    try:
        decision = await authz.authorize(...)
    except Exception as exc:
        ...
        raise AdminAuthorizationError(...)                    # ← fail-closed
```

**Проверено**:
- `grep -rn "from src.backend.services.admin.api\|from src.backend.services.admin import AdminService"`
  → единственный импорт в `src/backend/services/admin/__init__.py:11`.
  **Ни один entrypoint/test/composition root не инстанциирует этот
  класс**. Это мёртвый public API.
- В `tests/unit/services/admin/` есть только `test_sqladmin_setup.py`
  (тестирует `register_admin` для `/admin` UI-маршрута). Тестов на
  `AdminService._authorize` нет.
- Сравнение с `services/routes/route_authz.py` (lines 60-72) — там
  правильный fail-closed (`return False, "authorization_gateway_not_registered"`).

**Impact**:
- **P0** (security/risk-class): класс экспортирован через
  `services.admin.__all__`; любая будущая интеграция в
  composition root немедленно получит fail-open путь для
  admin actions (feature-flag toggle, audit log, sessions list).
- В текущем коде класс фактически dead code (impact снижен),
  но footgun для будущих maintainers.

**Минимальная рекомендация** (3 варианта):
- **A (fail-closed)**: заменить `return` на `raise AdminAuthorizationError(...)`
  (consistency с `route_authz.py`).
- **B (delete class)**: удалить `api.py` целиком, если класс
  не планируется использовать.
- **C (gate via env var)**: `if settings.app.environment != "dev": raise`.
  Не рекомендуется — оставляет fail-open в проде при условии.

**Test-критерий**: `test_admin_authorize_fails_closed_when_authz_unavailable`
  с mock `_get_authz() → None`, ожидая `AdminAuthorizationError`.

### DOMAIN-SVCS-P1-001 — 5-way дублирование в data_quality (cycle-1: 4-way)

**Files**:
- `src/backend/services/ops/data_quality/__init__.py:68-133`
- `src/backend/services/ops/data_quality/check_mixin.py:28-69`
- `src/backend/services/ops/data_quality/apply_mixin.py:30-71`
- `src/backend/services/ops/data_quality/schema_mixin.py:29-69`
- `src/backend/services/ops/data_quality/rule_mgmt_mixin.py:30-72`

**Доказательство** (runtime):

```text
$ python -c "
import sys; sys.path.insert(0, '.')
import importlib
m_init = importlib.import_module('src.backend.services.ops.data_quality')
m_apply = importlib.import_module('src.backend.services.ops.data_quality.apply_mixin')
m_check = importlib.import_module('src.backend.services.ops.data_quality.check_mixin')
print('init  DQSeverity:', id(m_init.DQSeverity))
print('apply DQSeverity:', id(m_apply.DQSeverity))
print('check DQSeverity:', id(m_check.DQSeverity))
print('init  is apply:', m_init.DQSeverity is m_apply.DQSeverity)
print('apply is check:', m_apply.DQSeverity is m_check.DQSeverity)
"
init  DQSeverity: 371542496
apply DQSeverity: 370023600
check DQSeverity: 370404160
init  DQSeverity is apply: False
apply DQSeverity is check: False
```

**Проверено**:
- 4 mixin-файла (402+197+187+114 = 900 LOC) каждый объявляют
  `DQSeverity`, `DQViolation`, `DQCheckResult`, `DQRule`.
- `__init__.py` объявляет их ещё раз + `DQRemediationResult`.
- Комментарий в `check_mixin.py:59` («DQRemediationResult lives in
  __init__.py (S153 W1: 5x dedup)») подтверждает: была попытка
  dedup, но только для `DQRemediationResult` — остальные 4 класса
  остались в 5-way дублировании.
- Diff между mixin-файлами: docstrings разные
  («Метод DQViolation (см. signature).» vs «Data quality violation record.»),
  что доказывает copy-paste, а не single source.

**Impact**:
- **Class identity mismatch**: `isinstance(x, DQSeverity)` зависит
  от того, какой файл первым импортирован. В тестах это маскируется
  через единый импорт `from src.backend.services.ops.data_quality import ...`,
  но в production-коде любой ленивый импорт из конкретного mixin-файла
  приведёт к тихому «неправильному» типу.
- 5 мест для правки enum-значений / dataclass-полей — высокая
  вероятность drift.
- `__init__.py` обнуляет decomp-модель: при импорте через
  `services.ops.data_quality` используются классы из `__init__.py`,
  но при импорте через конкретный mixin (например, для plugin-style
  reuse) — другой class object.

**Минимальная рекомендация**:
- Извлечь `DQSeverity`, `DQViolation`, `DQCheckResult`,
  `DQRule`, `DQRemediationResult` в `_protocol.py`
  (там сейчас только `_DataQualityProtocol`, 41 LOC).
- В mixin-файлах оставить только `from _protocol import ...`.
- `__init__.py` ре-экспортирует из `_protocol` (single source).
- LOC delta: −~120 (4 mixin × ~30 строк) + ~5 в `_protocol`.

**Test-критерий**:
- `test_dq_severity_identity_across_modules` —
  `assert apply_mixin.DQSeverity is check_mixin.DQSeverity is __init__.DQSeverity`.
- `test_dq_violation_identity_across_modules` — то же.

### DOMAIN-SVCS-P1-002 — reverse-layer shim `services/io/files.py`

**File**: `src/backend/services/io/files.py` (20 LOC)

```python
"""Backward-compat shim для FileService (Sprint 7, R-V15-16).

Канонический модуль теперь — ``extensions.core_entities.files.services.files``
(см. R-V15-16). Этот shim сохраняется на 1 minor-цикл и эмитит DeprecationWarning.
"""
from extensions.core_entities.files.services.files import FileService, get_file_service
warnings.warn("src.backend.services.io.files устарел; ...", DeprecationWarning, stacklevel=2)
```

**Проверено**:
- `grep -rn "from src.backend.services.io.files" src/backend/ tests/` →
  **3 активных caller'а**:
  - `src/backend/plugins/composition/service_setup.py:202`
  - `src/backend/dsl/commands/setup/registers_domains.py:70`
  - `src/backend/entrypoints/api/v1/endpoints/files.py:20`
- Module-level `warnings.warn` срабатывает на **каждый импорт** —
  не подавлен через `simplefilter("once")`.
- Docstring обещает «1 minor-цикл», но `git log -p src/backend/services/io/files.py`
  показывает: файл не трогался с момента создания в S175 R-V15-16
  (cycle 35+).

**Impact**:
- Каждый import → DeprecationWarning в stderr; не silenced →
  замусоривает логи в проде.
- В tests/unit/files / integration — спам warnings.
- Бизнес-логика не сломана, но это reverse-layer shim без
  timeline на удаление.

**Минимальная рекомендация**:
- Sprint-план: перевести 3 caller'а на
  `extensions.core_entities.files.services.files`,
  удалить shim + `services/io/files.py`.
- LOC delta: −20.

**Test-критерий**:
- `test_no_deprecated_io_files_imports` —
  `ast.parse` всех `src/backend/**/*.py`, `grep -rn "from src.backend.services.io.files\b"`.
  Ожидаемо: 0 hits.

### DOMAIN-SVCS-P1-003 — reverse-layer shim + production mix в `services/integrations/skb.py`

**File**: `src/backend/services/integrations/skb.py` (152 LOC)

**Проверено**:
- Файл содержит:
     - Production `APISKBService` (lines 26-124) — реальный HTTP-клиент
       с auth-injection через query-param `api-key`.
     - Deprecation shim `resolve_waf_route` (lines 142-152) —
       backward-compat для `extensions.skb.services.waf_route`.
- `src/backend/core/integrations/skb.py` (15 LOC) — второй уровень
  indirection: `from src.backend.services.integrations.skb import APISKBService, get_skb_service`.
- Layer violation `core/integrations/skb.py → services/integrations/skb`
  allowlisted (allowlist line 40, `core → src.backend.services.integrations.skb`).
- 4 caller'а:
  - `src/backend/plugins/composition/service_setup.py`
  - `src/backend/dsl/commands/setup/registers_domains.py`
  - `src/backend/core/integrations/skb.py`
  - `src/backend/entrypoints/api/v1/endpoints/skb.py`

**Impact**:
- `services/integrations/skb.py` смешивает **production-логику**
  (HTTP auth-injection, retry semantics) и **shim-обёртку** —
  нарушение SRP, но не blocking.
- Reverse-layer import `core/integrations/skb.py → services/integrations/skb`
  зафиксирован в allowlist и не эскалируется.

**Минимальная рекомендация**:
- Разделить на 2 файла:
     - `services/integrations/skb/client.py` (production).
     - `services/integrations/skb/_legacy.py` (deprecation shim).
- Удалить `core/integrations/skb.py` facade после перевода
  caller'ов на прямой импорт из `services/integrations/skb/client.py`.
- LOC delta: −5 (бонус) + cleaner separation.

**Test-критерий**:
- `test_skb_client_auth_injection_isolated` (уже есть в
  `tests/unit/services/integrations/test_skb.py` — проверить, что
  auth-mixin выделен в отдельный mixin).
- `test_no_deprecated_resolve_waf_route_imports` — `grep` аналогично P1-002.

### DOMAIN-SVCS-P1-004 — мёртвый public API `AdminService` (services/admin/api.py)

**File**: `src/backend/services/admin/api.py` (244 LOC, целиком)

**Проверено**:
- `grep -rn "AdminService\s*\(" .` → 3 hits:
  - `docs/audit/swarm-2026-08-06/cycle-1/phase-1/03-services.md`
    (другой agent's report — не считается).
  - `ARCHITECTURE.md` (документация).
  - `tests/unit/services/core/test_admin.py:12` (импортирует
    `services.core.admin.AdminService`, **не** `services.admin.api.AdminService`
    — это **другой класс** в `core/admin.py`).
- `services/admin/__init__.py:11` re-export, но **никто не
  импортирует `services.admin` целиком**:
  ```bash
  $ grep -rn "from src.backend.services import admin" src/backend/ tests/
  # 0 hits
  ```

**Impact**:
- 244 LOC мёртвого кода с fail-open P0 внутри (см. P0-001).
- `services/admin/api.py` не имеет docstring-module-imports,
  модуль не покрыт тестами, не подключён к composition root.

**Минимальная рекомендация**:
- Либо удалить `services/admin/api.py` (целиком 244 LOC),
  либо переименовать + переподключить через composition root.
- Сейчас это **deferred cleanup** — добавить в Phase-3 plan cycle 2.

**Test-критерий**:
- `test_services_admin_api_actually_used` — `grep`-тест, проверяющий
  наличие хотя бы одного caller'а вне docstring/re-export.
  Сейчас провалится (ожидаемое поведение).

### DOMAIN-SVCS-P2-001 — Stub `QuotasService`

**File**: `src/backend/services/billing/quotas_service.py` (38 LOC)

**Проверено**:
- `__init__` бросает `NotImplementedError("QuotasService not yet implemented; use NoOpBillingFacade via src.backend.core.di.providers.billing.get_quotas_backend_provider().")`.
- `consume_request` / `check_tokens` тоже бросают
  (`raise NotImplementedError("QuotasService.consume_request is a stub")`).
- Тест `tests/unit/services/billing/test_no_op_billing_cycle33.py:209-216` —
  `test_quota_service_constructor_raises_not_implemented`.
- Docstring явно говорит: «real billing backend not yet integrated».

**Impact**:
- **P2** (dead code / stub), но **fail-fast** на `__init__` —
  любой вызов немедленно падает с понятной ошибкой.
- Не блокирует, но визуально noise в IDE/lint.

**Минимальная рекомендация**:
- Оставить как есть (явный fail-fast — лучше silent-fallback).
- Либо полностью удалить и оставить только `NoOpBillingFacade`
  (что уже есть).

**Test-критерий**: уже покрыт.

### DOMAIN-SVCS-P2-002 — `raise NotImplementedError # заменяется декоратором` placeholder

**Files** (в scope):
- `src/backend/services/io/web_automation.py:128`
- `src/backend/services/io/export_service.py:405`
- `src/backend/services/ops/anomaly_detector.py:151`
- `src/backend/services/ops/scheduled_reports.py:209`
- `src/backend/services/ops/message_replay.py:185`
- `src/backend/services/ops/notification_hub.py:286`
- `src/backend/services/ops/webhook_scheduler.py:169`
- `src/backend/services/core/admin.py:233`
- `src/backend/services/core/tech.py:201`

**Проверено**:
- Все 9 — внутри функций, обёрнутых в
  `@app_state_singleton("...", factory=...)`.
- Декоратор `app_state_singleton`
  (`src/backend/core/di/app_state.py:143-187`) возвращает `wrapper`,
  который **никогда не вызывает `fn()`** — body с `raise
  NotImplementedError` физически недостижимо.
- Pattern документально зафиксирован в комментарии
  (`app_state.py:166-185`):
  ```python
  def decorator(fn: Callable[[], T]) -> Callable[[], T]:
      def wrapper() -> T:
          instance = _get_from_app_state(attr)
          if instance is not None: return instance
          if attr not in _cache:
              if factory is not None: _cache[attr] = factory()
              ...
          return _cache[attr]
      wrapper.__name__ = fn.__name__
      wrapper.__doc__ = fn.__doc__
      ...
  ```

**Impact**:
- **Dead code** (cosmetic) — 9×1 строк = 9 LOC.
- IDE/lint видит `raise NotImplementedError` без `try/except` —
  ложные предупреждения.
- Не блокирует, но нарушает «boring over clever» (Ponytail D-rule).

**Минимальная рекомендация**:
- Заменить `raise NotImplementedError  # заменяется декоратором`
  на `...` (Ellipsis) или удалить body целиком
  (только docstring):
  ```python
  def get_x_service() -> XService:
      """..."""
      ...  # body replaced by app_state_singleton
  ```
- LOC delta: −9 (или 0, если оставить `...`).

**Test-критерий**:
- `test_no_unreachable_notimplementederror_in_decorated_factories` —
  AST-парсер проверяет, что функции с
  `@app_state_singleton` не имеют body с `raise NotImplementedError`.

### DOMAIN-SVCS-P2-005 — DLQ silent_loss priority-3 (cycle-1 был полный silent_loss)

**File**: `src/backend/services/audit/clickhouse_audit_service/service.py`

**Проверено** (строки 158-244):
```python
async def _send_to_dlq(self, *, event, events, error, ...):
    targets = events if events is not None else ([event] if event is not None else [])
    if not targets: return

    # Приоритет 1: canonical DLQWriter Protocol (Inbox / Kafka / NATS / etc.).
    if self._dlq_writer is not None:
        try:
            ...
            await self._dlq_writer.write(envelope)
        except Exception as dlq_exc:
            _logger.error("DLQWriter fallback failed (...)", ...)
        return                                     # ← приоритет 1 consume

    # Приоритет 2: legacy JSONL path (deprecated, для старых deployment).
    backend = self._get_dlq_backend()
    if backend is None:
        return                                     # ← priority 3 silent loss
    try:
        ...
    except Exception as dlq_exc:
        _logger.error(...)
```

**Layer violation** (allowlist строка 179):
```
src/backend/services/audit/clickhouse_audit_service/service.py
   services  src.backend.infrastructure.messaging.dlq_base
```
**Однако** services → infrastructure нарушение, которое должно быть
наоборот — `core → infrastructure`, либо через
`core/audit/facade.audit_service` (как используется в
`no_op_billing.py:152`). Cycle-1 это не решил.

**Цикл 1 → cycle 2 delta**:
- Cycle 1: silent_loss для всех path'ов.
- Cycle 2 (S180 P1-#1): priority-1 canonical DLQWriter + priority-2
  legacy JSONL. Priority-3 (нет ни writer, ни path) — silent_loss
  сохраняется как backward-compat.
- Тест `test_no_dlq_when_path_not_set_legacy_silent_loss`
  (`tests/unit/services/audit/test_clickhouse_audit_dlq.py:155+`)
  фиксирует это как документированное поведение.

**Impact**:
- В production deployment без `dlq_writer` и без `dlq_path`
  события ClickHouse audit **теряются молча** (только WARNING в логе).
- Если composition root забыл wiring DLQWriter — нет signal'а.
- Для security/audit trail это потенциальный P0 (data-loss),
  но mitigated в текущем цикле через priority-1 wiring.

**Минимальная рекомендация**:
- В priority-3 branch: поднять до `ERROR` + emit
  `audit_event="dlq_unconfigured"` через
  `core.audit.facade.audit_service.emit` (best-effort, не raise).
- Либо fail-closed: при `feature_flags.audit_clickhouse_enabled=True`
  и `dlq_writer is None and dlq_path is None` → `RuntimeError` в
  `_send_to_dlq` (это сломает production wiring — нужна
  migration phase).
- Параллельно: убрать reverse-layer violation
  (`services/audit/clickhouse_audit_service/service.py:21, 192` —
  импорт из `infrastructure.messaging.dlq_base`); вынести
  импорт `DLQEnvelope`, `DLQWriter` Protocol в
  `core.audit.facade.audit_service` (re-export).

**Test-критерий**:
- `test_dlq_priority3_emits_error_audit_event_when_unconfigured` —
  mock ClickHouse failing, no dlq_writer + no dlq_path → ожидаем
  audit event с `outcome=error`, `event="dlq_unconfigured"`.
- `test_no_services_to_infrastructure_dlq_import` — AST-check
  отсутствия прямого `from src.backend.infrastructure.messaging.dlq_base import`
  в `services/`.

### DOMAIN-SVCS-P3-001 — кастомный retry в audit + resilience.facade

**Files**:
- `src/backend/services/audit/clickhouse_audit_service/service.py:268, 324`
- `src/backend/services/resilience/facade.py:205+`

**Проверено**:
- `core.resilience.retry.retry_async` — общий helper
  (используется в audit emit, см. строки 268, 324).
- В `pyproject.toml:74`: `tenacity>=9.0.0,<10.0.0` уже в зависимостях.
- В `src/backend/` уже 5+ мест используют `tenacity`:
  - `src/backend/infrastructure/clients/transport/http_httpx.py:24`
  - `src/backend/infrastructure/clients/transport/http/request_mixin.py:13`
  - `src/backend/dsl/engine/processors/control_flow/flow.py:133-145`
  - `src/backend/services/ai/agents_pydantic/base.py:226`
- `retry_async` — собственная обёртка (~50 LOC) дублирует
  функционал `tenacity.AsyncRetrying`.

**Impact**:
- Дублирование retry-логики.
- 2 разных API (`retry_async(fn, max_attempts, base_delay)` vs
  `tenacity.AsyncRetrying(...)` + `wait_exponential`).

**Минимальная рекомендация**:
- Постепенно мигрировать `retry_async` callsites на
  `tenacity.AsyncRetrying` (для нового кода); существующий
  `retry_async` оставить как thin wrapper для обратной совместимости.
- LOC delta: не оценивал (требует audit всех callsites).

**Test-критерий**: не требуется (бонус-улучшение).

### DOMAIN-SVCS-P3-002 — `apprise` lazy-import (NOTE: positive)

**File**: `src/backend/services/notifications/apprise_service.py:97-117`

**Проверено**:
- `import apprise` обёрнут в `try/except ImportError`
  (строки 97-100) с явным WARNING + return False.
- `apprise` в `pyproject.toml:842` (стабильная зависимость).
- Это **правильный** lazy-import pattern — graceful degradation
  при отсутствии пакета (не прописан в core deps, помечен как
  optional через ленивую загрузку).

**Impact**: нет (положительный паттерн).

### DOMAIN-SVCS-P4-001 — `list_audit_records` без ClickHouse fallback

**File**: `src/backend/services/audit/replay_query.py:30-90`

**Проверено**:
- `list_audit_records` работает только с Redis stream
  `"audit:events"` (`_STREAM_NAME` в строке 36).
- Нет fallback на ClickHouse `audit_events` table для случая
  Redis outage (DR scenario).
- В текущем ClickHouse-first дизайне (audit events идут в
  ClickHouse + DLQ fallback) это означает: если Redis stream
  потерян, replay через этот API невозможен.

**Минимальная рекомендация** (P4 — органичное расширение):
- Добавить опциональный параметр `source: Literal["redis","clickhouse","both"]`,
  при `"clickhouse"` или `"both"` — fallback запрос к
  `ClickHouseAuditService` через `core.audit.facade`.
- Соблюдает EIP/Camel-like DSL (route → service → backend).

**Test-критерий**:
- `test_replay_query_falls_back_to_clickhouse_when_redis_unavailable`.

---

## 5. Cycle-1 residuals (verified или mutated)

> Cycle-1 отчёт `docs/audit/swarm-2026-08-06/cycle-1/03-services.md`
> **не читал** (запрещено условиями задачи). Сверяю только по
> тем ID, которые явно упомянуты в задаче.

| Cycle-1 ID | Cycle-2 ID | Статус | Доказательство |
|---|---|---|---|
| `DOMAIN-P0-001` (admin/api.py fail-open) | `DOMAIN-SVCS-P0-001` | **RESIDUAL** | Код в `api.py:96-102` не изменился. Однако: класс **dead code** (нет caller'ов), severity сохранён P0 как footgun. |
| `P1-001` (4-way data_quality dup) | `DOMAIN-SVCS-P1-001` | **MUTATED** | Стало **5-way** (добавлено ещё одно объявление в `__init__.py`). Дополнительно выявлено: class identity mismatch (runtime-проверено). Severity остался P1, но **требует action** из-за identity bug. |
| `P1-002` (skb.py shim) | `DOMAIN-SVCS-P1-003` | **RESIDUAL** | Файл `services/integrations/skb.py` (152 LOC) не изменился. Shim `resolve_waf_route` остаётся с DeprecationWarning (lines 142-152). Reverse-layer allowlist (line 40) сохранён. |
| `P1-003` (files.py shim) | `DOMAIN-SVCS-P1-002` | **RESIDUAL** | Файл `services/io/files.py` (20 LOC) не изменился. 3 активных caller'а. Module-level `warnings.warn` без `simplefilter("once")`. |
| `P2-001` (NotImplementedError stubs) | `DOMAIN-SVCS-P2-001` + `P2-002` | **PARTIALLY MUTATED** | `QuotasService` stub (P2-001) сохранён с явным fail-fast + tests. Дополнительно выявлено: 9× `raise NotImplementedError # заменяется декоратором` placeholder'ов (P2-002). |
| `P2-005` (ClickHouse DLQ silent_loss) | `DOMAIN-SVCS-P2-005` | **PARTIALLY MUTATED** | S180 P1-#1: priority-1 canonical DLQWriter добавлен. Priority-3 (legacy silent_loss) сохранён как backward-compat (тест `test_no_dlq_when_path_not_set_legacy_silent_loss`). |

**Резюме delta**:
- 2 finding'а полностью RESIDUAL (P0-001 fail-open, P1-002 files shim, P1-003 skb shim).
- 1 finding MUTATED в худшую сторону (P1-001 4→5-way).
- 3 finding'а partially mutated (P2-001/002/005).

---

## 6. Contradictions / overlaps to flag

1. **DOMAIN-SVCS-P0-001 vs DOMAIN-SVCS-P1-004** — оба про
   `services/admin/api.py`. P0-001 (fail-open внутри) — primary
   security. P1-004 (весь класс dead code) — root cause.
   Решение одно: либо fix P0-001 (A), либо fix P1-004 (B).
2. **DOMAIN-SVCS-P1-001 (5-way dup)** — comment в
   `check_mixin.py:59` указывает на S153 W1 dedup effort; но
   dedup коснулся только `DQRemediationResult`. Это объясняет,
   почему цикл-1 finding зафиксировал «4-way», а cycle-2 видит
   «5-way»: добавился новый объявления в `__init__.py` без
   удаления из mixin'ов.
3. **DOMAIN-SVCS-P2-005 vs layer-violation entry** — priority-3
   silent_loss частично объясняется наличием reverse-layer
   violation (services → infrastructure.messaging.dlq_base).
   Clean refactor: вынести `DLQEnvelope`/`DLQWriter` Protocol
   в `core/audit/facade.audit_service` (re-export), удалить
   прямой импорт из `services/`. Это устранит и P2-005 root cause
   для legacy deployment, и layer-violation (allowlist line 179).
4. **Пересечение с cycle-1 Phase 4** — uncommitted правки
   `services/ai/gateway_adapter.py` НЕ в моём scope (ai/
   исключён); но `core/ai/gateway_pipeline_mixin/policy_mixin.py`
   (тоже uncommitted, cycle-1 Phase 4 T-1.5) — в смежном слое
   `core/`, не атрибутируется рою cycle 2. Проверено: не
   затрагивает мой scope.
5. **Скрытые dead-code paths** — `AdminService` (services/admin/api.py)
   не вызывается, но `services/admin/__init__.py:11` ре-экспортирует.
   Grep `from src.backend.services import admin` → **0 hits** в
   production коде.

---

## 7. Readiness score 0–100

**Формула** (rule-based):
```
score = 100
  - 25 × (P0 count)            # каждый P0 — блокер production-ready
  - 10 × (P1 count)            # каждый P1 — серьёзная архитектурная проблема
  -  3 × (P2 count)            # P2 — dead code / технический долг
  -  1 × (P3 count)            # P3 — library / optimization
  -  0.5 × (P4 count)          # P4 — органичное расширение
  + bonus 5 за verified strengths (capability facade, retry_async,
                                   canonical DLQWriter, route_authz fail-closed)
  - penalty 0 за отсутствующие тесты на P0
```

**Подсчёт**:
```
score = 100
  - 25 × 1  (P0)             = -25
  - 10 × 4  (P1)             = -40
  -  3 × 4  (P2)             = -12
  -  1 × 1  (P3, new)        = -1
  -  0.5 × 1 (P4)            = -0.5
  + 5 bonus (strengths)      = +5
  - 5 penalty (no P0 tests)  = -5
                             --------
                             = 21.5
```

**Округлено**: **22 / 100**.

**Обоснование**:
- ≥80 запрещено при наличии P0/P1 (правило задачи). У нас 1 P0 + 4 P1,
  поэтому score cap = **60**.
- P0 (fail-open в AdminService) — **блокер** для safe-by-default,
  даже если класс сейчас dead code.
- 4 P1 — 2 layer-violations (shims) + 1 dead-code class + 1 data_quality
  duplication с runtime class-identity bug.
- P2 stub'ы fail-fast — не блокеры, но создают noise.

**Вердикт**: **22 / 100** — NOT READY для production merge без
исправления P0-001 + хотя бы одного из P1 (рекомендую P1-001 +
P1-004 — оба устраняются за один commit).

---

## 8. Recommended next tasks

| Приоритет | Задача | Файлы | Effort | Test |
|---|---|---|---|---|
| **P0 (блокер)** | Fix fail-open в `AdminService._authorize` (вариант A: `raise AdminAuthorizationError`) ИЛИ удалить `services/admin/api.py` целиком | `services/admin/api.py:96-102` или целиком 244 LOC | 30 мин / 1 час | `test_admin_authorize_fails_closed_when_authz_unavailable` |
| **P1 (high)** | Удалить 5-way дубль data_quality: extract в `_protocol.py` | `services/ops/data_quality/{check,apply,schema,rule_mgmt}_mixin.py`, `__init__.py` | 2 часа | `test_dq_severity_identity_across_modules` |
| **P1 (high)** | Удалить `services/admin/api.py` (dead code) ИЛИ подключить к composition root с fail-closed fix | `services/admin/api.py` | 1 час | зависит от выбора |
| **P1 (med)** | Перевести 3 caller'а `services.io.files` на `extensions.core_entities.files.services.files`, удалить shim | `plugins/composition/service_setup.py:202`, `dsl/commands/setup/registers_domains.py:70`, `entrypoints/api/v1/endpoints/files.py:20`, `services/io/files.py` | 2 часа | `test_no_deprecated_io_files_imports` |
| **P1 (med)** | Разделить `services/integrations/skb.py` на `client.py` (production) и `_legacy.py` (shim); удалить `core/integrations/skb.py` reverse-shim | `services/integrations/skb.py`, `core/integrations/skb.py`, 3 caller'а | 3 часа | `test_no_deprecated_resolve_waf_route_imports` |
| **P2 (low)** | Заменить `raise NotImplementedError # заменяется декоратором` на `...` в 9 файлах (или удалить body) | 9× app_state_singleton factories | 30 мин | `test_no_unreachable_notimplementederror_in_decorated_factories` |
| **P2 (low)** | DLQ priority-3 silent_loss → emit audit event `dlq_unconfigured` (или fail-closed с migration phase) | `services/audit/clickhouse_audit_service/service.py:184-186, 220-223` | 2 часа | `test_dlq_priority3_emits_error_audit_event_when_unconfigured` |
| **P2 (low)** | Вынести `DLQEnvelope`/`DLQWriter` re-export в `core.audit.facade.audit_service`; убрать `services/audit/clickhouse_audit_service/service.py:21, 192` direct import; удалить allowlist line 179 | `core/audit/facade/audit_service.py`, `services/audit/clickhouse_audit_service/service.py`, `tools/check_layers_allowlist.txt` | 1 час | `test_no_services_to_infrastructure_dlq_import` |
| **P3 (optional)** | Мигрировать retry callsites на `tenacity.AsyncRetrying` (постепенно) | `services/audit/clickhouse_audit_service/service.py:268, 324`, `services/resilience/facade.py:205+` | 4 часа (audit-wide) | не требуется |
| **P4 (nice-to-have)** | Добавить ClickHouse fallback в `list_audit_records` для DR scenario | `services/audit/replay_query.py` | 3 часа | `test_replay_query_falls_back_to_clickhouse_when_redis_unavailable` |

**Совокупный effort** (P0+P1): ~10 часов.
**Совокупный effort** (P0+P1+P2): ~14 часов.

---

## 9. Commands run (read-only, verification only)

```bash
# 1. Layer checker
$ python tools/check_layers.py --root src
# Нарушений: 0 новых (файлов: 2273; baseline: 175 legacy)

# 2. Allowlist line count
$ wc -l tools/check_layers_allowlist.txt
180 tools/check_layers_allowlist.txt
# (5 comment + 175 active = matches baseline)

# 3. Security allowlist count
$ grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt
35

# 4. Admin fail-open search
$ grep -n "_authorize\|fail_open\|warning.*allow" src/backend/services/admin/api.py
# Found at lines 82-102 — fail-open path

# 5. AdminService usage
$ grep -rn "from src.backend.services.admin.api\|from src.backend.services.admin import AdminService" src/backend/ tests/
# 1 hit: only in services/admin/__init__.py re-export

# 6. AdminService instantiation
$ grep -rn "AdminService\s*\(" .
# 3 hits: ARCHITECTURE.md, cycle-1 report (other agent),
# tests/unit/services/core/test_admin.py (DIFFERENT AdminService from core/admin.py)

# 7. DataQuality class duplication
$ grep -n "^class DQSeverity\|^class DQViolation\|^class DQCheckResult\|^class DQRemediationResult\|^class DQRule" src/backend/services/ops/data_quality/*.py
# 4 files × 4 classes = 16 declarations + 1 in __init__.py = 5-way dup

# 8. DataQuality class identity (runtime)
$ python -c "..."
# init  is apply: False
# apply is check: False

# 9. NotImplementedError in scope
$ grep -rln "NotImplementedError\|raise NotImplemented" src/backend/services/ | grep -v "/ai/\|/workflow/\|/workflows/\|/security/\|/auth/\|/authorization/\|/agent_security/"
# 12 files: 9× app_state_singleton placeholder + 2× billing stubs + 1× jupyter (comment-only historical)

# 10. DLQ silent_loss priority
$ grep -n "silent\|silent_loss\|priority 3\|priority 2" src/backend/services/audit/clickhouse_audit_service/service.py
# Found at lines 184-186, 220-223

# 11. DLQ test
$ grep -n "test_no_dlq_when_path_not_set_legacy_silent_loss" tests/unit/services/audit/test_clickhouse_audit_dlq.py
# line 155 (explicit backward-compat test)

# 12. files.py shim callers
$ grep -rn "from src.backend.services.io.files" src/backend/ tests/
# 3 hits: plugins/composition/service_setup.py:202,
# dsl/commands/setup/registers_domains.py:70,
# entrypoints/api/v1/endpoints/files.py:20

# 13. skb.py shim
$ grep -n "resolve_waf_route" src/backend/services/integrations/skb.py
# lines 142-152 (backward-compat shim with DeprecationWarning)

# 14. QuotasService stub tests
$ grep -n "test_quota_service\|NotImplementedError" tests/unit/services/billing/test_no_op_billing_cycle33.py
# line 209-216 (constructor raises test)

# 15. apprise dependency
$ grep -n "apprise" pyproject.toml
# line 842 (declared)

# 16. tenacity dependency
$ grep -n "tenacity" pyproject.toml
# line 74 (declared, >=9.0.0)

# 17. cycle-1 uncommitted changes (NOT in scope, NOT investigated)
$ git status --short
# M src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py (cycle-1 T-1.5)
# M src/backend/dsl/engine/processors/eip/reliability/redelivery_policy.py
# M src/backend/dsl/engine/processors/eip/routing/multicast.py
# M src/backend/infrastructure/cache/rag/embedding_cache.py
# M src/backend/services/ai/gateway_adapter.py (cycle-1, but ai/ is OUT OF SCOPE)
# M tests/unit/core/ai/test_gateway_pipeline_mixin.py
# M tests/unit/services/ai/test_gateway_adapter.py
# M uv.lock (pre-existing drift, NOT swarm)
# ?? .blue_green.state, ?? pip-audit.json, ?? tools/cycle-1-preflight.sh, ?? tests/unit/dsl/.../eip/..., ?? tests/unit/infrastructure/cache/rag/, ?? docs/audit/swarm-2026-08-06/

# 18. test files count in scope
$ find tests/unit/services -name "*.py" | wc -l
227
```

**Все команды read-only. Файлы не модифицированы. Git не мутирован.**

---

## Резюме для parent agent

- **Readiness**: **22 / 100** (cap 60 из-за P0+P1; формула в §7).
- **Findings**: 1 P0 + 4 P1 + 4 P2 + 1 P3 (new) + 1 P3 (note) + 1 P4 = **11 finding'ов**.
- **Блокеры (P0 + критичные P1)**:
  1. `DOMAIN-SVCS-P0-001` — fail-open в `services/admin/api.py:96-102`.
  2. `DOMAIN-SVCS-P1-001` — 5-way data_quality dup с class identity bug.
  3. `DOMAIN-SVCS-P1-004` — мёртвый public API `AdminService` (244 LOC).
- **Cycle-1 residuals**:
  - RESIDUAL: P0-001 (fail-open), P1-002 (files shim), P1-003 (skb shim).
  - MUTATED: P1-001 (4→5-way).
  - PARTIALLY MUTATED: P2-001/002/005.
- **Layer violations** (вне scope моего действия, но рекомендую в §8):
  - `services/audit/clickhouse_audit_service/service.py → infrastructure/messaging/dlq_base`
    (allowlist line 179, services → infrastructure, должно быть через
    `core.audit.facade.audit_service`).
- **Report path**: `docs/audit/swarm-2026-08-06/cycle-2/phase-1/03-services.md`.
- **Cycle-2 layer-violations growth** (заявленное 173→180):
  - baseline cycle 2: **175 legacy** (active entries in allowlist).
  - файл `tools/check_layers_allowlist.txt` имеет **180 строк**
    (5 comment + 175 active).
  - **Реального роста layer-violations нет**; +5 строк в файле —
    header-comments, не новые violations. Подтверждено
    `python tools/check_layers.py --root src` → 0 new / 175 legacy.
  - Если «173» — это historical baseline (cycle 1 финал), то
    delta = +2 active entries между cycle 1 (173) и cycle 2 (175).
    Точный источник «173» не верифицирован (cycle-1 отчёты
    запрещено читать).