# Cycle 4 — Phase 1 — Домен Бизнес-логика (Business Logic)

- Аналитик: Kimi Code CLI (subagent, business-logic domain)
- Дата: 2026-08-07
- HEAD: `22e08a0d` (cycle-1/2/3 reapply commit, +1 over cycle-3 baseline)
- Scope: `extensions/**` + `tests/` внутри `extensions/` (по условию задачи)
- Baseline: `docs/audit/swarm-2026-08-06/cycle-4/BASELINE.md`

---

## Scope / не проверено

**Проверено (read-only, через `.venv/bin/python`):**

- `extensions/credit_pipeline/**` (plugin, agents, services, workflows, tests, plugin.toml)
- `extensions/osint_agent/**` (plugin, functions, tests)
- `extensions/core_admin/**` (schemas-only)
- `extensions/core_entities/{files,orders,orderkinds,users}/**` (plugin, services, repositories, schemas, models, workflows, tests)
- `extensions/dadata/**`, `extensions/skb/**` (schemas-only)
- `extensions/test_plug/**`
- `extensions/__init__.py`
- `tools/checks/check_workflows_extensions.py` (workflow extensions gate)
- Контрактные части `src/backend/dsl/workflow/builder/*` (sla_mixin, wait_mixin, workflow_mixin) и `src/backend/dsl/workflow/spec/activity_declarations.py` — для cross-reference (только чтобы проверить корректность API, который потребляют extensions). Сам `src/` для целей аудита **не анализировался**, только в части валидации контракта, который обязаны выполнять extensions.
- `src/backend/services/tenancy/facade.py` — только в части перепроверки T-08 (TenantFacade kwargs fix).
- `src/backend/core/feature_flags` — только в части перепроверки T-09 (credit_pipeline_v2 default).

**Не проверено (вне scope или запрещено условием):**

- Cycle-1/2/3 markdown-отчёты других агентов (запрет).
- `KNOWN_ISSUES.md`, `CLAUDE.md`, `PLAN.md`, `DEEP_AUDIT_REPORT.md`, `triage_allowlist_report.md` (запрет).
- Полный аудит `src/backend/**` (вне scope — это задачи других аналитиков).
- Cross-cutting concerns (security, infra, observability) — другие домены.
- Pre-existing residuals в `src/backend/services/ai/gateway_adapter.py:128-129`, `tests/unit/core/ai/test_gateway_pipeline_mixin.py:54` — `BASELINE.md` явно указывает, что они НЕ этому swarm.

**Цикл 4 baseline учтён:** HEAD 22e08a0d; 8 правок cycle 1+2+3 (T-1.4/T-1.5/T-3.1/T-W1-01/T-W1-05/T-W1-08 + T-02/T-03) уже в HEAD — НЕ атрибутируются рою cycle 4.

---

## Verified strengths

1. **T-W1-08 credit scoring fail-CLOSED — VERIFIED LIVE.** `extensions/credit_pipeline/agents/__init__.py:79-111` имеет ветку `unknown_tenant` (income <= 0 или amount <= 0 → `credit_score=0`, `risk_class=HIGH`, `reason="unknown_tenant"`). Прямой прогон через `.venv/bin/python` (4 кейса: пустой payload, income=0, amount=0, валидный) подтвердил: `risk_class=HIGH, credit_score=0` в трёх fail-кейсах; `risk_class=LOW, credit_score=800` в валидном. Audit emission через `emit_audit_safe` (best-effort) присутствует.

2. **credit_pipeline actions real implementation.** `extensions/credit_pipeline/plugin.py:108-110` регистрирует 3 real actions (`score`/`parse`/`decide`), каждый обёрнут в `_make_handler` factory. Тесты `test_actions_registration.py` — 8/8 PASS (включая chain score→decide, idempotent re-registration, propagation of exceptions).

3. **SKB client fail-CLOSED на внешних вызовах.** `extensions/credit_pipeline/services/clients/skb.py:92,106,132` — все три метода (`get_request_kinds`, `create_request`, `get_result`) оборачивают исключения в `raise ServiceError from exc`. Per-service timeout через `BaseExternalAPIClient + SKBAPISettings` (R-V15-13). WAF-routing для production через `_waf_route()`. Auth через query-param `api-key`.

4. **core_entities (files/orders/users/orderkinds) — repository pattern + tenant-aware.** `extensions/core_entities/orders/repositories/orders.py:69-95` использует `main_session_manager.connection()` decorator (DB-session management). `OrderRepository` наследует `SQLAlchemyRepository`, имеет DI для `OrderKindRepository`. Все 35 тестов в `extensions/core_entities/` PASS (35 passed, 0 failed).

5. **DSL workflow saga через builder method.** `extensions/core_entities/orders/workflows/orders_dsl.py:175-186,195-214,266-281` — три saga-based workflow spec'а (`send_notification`, `create_skb_order`, `send_skb_result`) корректно собираются через `.saga().forward().compensate().end_saga().build()`. Verify: `.venv/bin/python -c` — 3/3 OK, шаг имеет `type='saga'`.

6. **Plugin trust_tier="A" на всех банковских extension.** `extensions/credit_pipeline/plugin.toml:22`, `extensions/dadata/plugin.toml:9`, `extensions/skb/plugin.toml:9`, `extensions/core_admin/plugin.toml:9` — все `trust_tier="A"`. Per D-AUDIT-FIX-184-5 (2026-08-05).

7. **credit_assessment workflow YAML fail-CLOSED по умолчанию.** `extensions/credit_pipeline/workflows/credit_assessment.workflow.yaml:81` — `default_decision: REJECT` в rule_engine. BPMN-like compensation chain (saga rollback) присутствует (строки 91-96).

8. **OSINT INN validation — checksum корректен для 10-digit.** `src/backend/dsl/helpers/banking.py:31-43` — `validate_inn("7707083893")` → True (Sberbank контрольная сумма сходится). Smoke-тесты `test_osint_workflow.py::TestValidateInn` — 5/7 PASS.

9. **Layer boundaries в extensions соблюдены.** `extensions/*` импортирует ТОЛЬКО из `src.backend.core.*` (capability-checked facades) и `extensions/*` (cross-extensions references). Контрактный gate `tools/checks/check_workflows_extensions.py` — exit 0.

10. **T-08 TenantFacade with_tenant contract documented** (S193 fix). `src/backend/services/tenancy/facade.py:96-124` — `with_tenant(tenant_id, principal_id)` использует `CapabilityTenant`. Контракт задокументирован в docstring, **но реализация содержит bug** (см. BL-P1-002 ниже).

---

## Findings table

| ID | Priority | Path:line | Краткое описание |
|---|---|---|---|
| BL-P0-001 | P0 | `extensions/osint_agent/functions/osint_workflow.py:333-334` | OSINT fail-OPEN при LLM failure: `raw_text = prompt` (echo template как report) |
| BL-P0-002 | P0 | `extensions/osint_agent/functions/osint_workflow.py:307-313` | OSINT fail-OPEN при search failure: LLM галлюцинирует без данных |
| BL-P1-001 | P1 | `extensions/core_entities/orders/workflows/orders_dsl.py:241,250,305,315,316,326,336` | WorkflowBuilder `.then()` method does NOT exist → AttributeError при вызове `poll_skb_result_workflow_spec()` / `order_processing_workflow_spec()` |
| BL-P1-002 | P1 | `src/backend/services/tenancy/facade.py:116-119` (consumed by extensions) | TenantFacade.with_tenant() вызывает `CapabilityTenant(tenant_id=..., principal_id=...)` — неправильные kwargs (правильно `id=, principal=`) → TypeError |
| BL-P1-003 | P1 | `src/backend/dsl/helpers/banking.py:31-43` (consumed by OSINT) | `validate_inn(None)` raises TypeError вместо fail-CLOSED `False` |
| BL-P2-001 | P2 | `extensions/core_entities/orders/workflows/orders_dsl.py:37` | Dead import `SagaDeclaration` (0 references, 0 instantiations) |
| BL-P2-002 | P2 | `extensions/osint_agent/tests/test_osint_workflow.py:26` | Test data `"770708389307"` — invalid 12-digit INN checksum (TEST BUG, не code bug) |
| BL-P2-003 | P2 | `src/backend/core/config/features/plugins.py:41-52` (RESIDUAL cycle-3 T-09) | `credit_pipeline_v2: bool = Field(default=True, ...)` — description говорит "default-OFF", test expects default-OFF, но реальный default = True |
| BL-P2-004 | P2 | `extensions/core_entities/orders/services/orders.py:112-113,125-126` | `except Exception: return` (noqa BLE001) в `_index_order_async` / `_delete_order_index_async` — silent ES indexing failures (legitimate fire-and-forget, but no observability) |
| BL-P3-001 | P3 | `extensions/osint_agent/functions/osint_workflow.py:239,264,275,310,333` | 5× `except Exception` broad catch с fallback (graceful degradation). Уместно для graceful, но masking unexpected errors. |
| BL-P3-002 | P3 | `extensions/credit_pipeline/agents/__init__.py:101-103` | `except Exception: pass` — swallow всех audit emission failures (no logger.warning) |
| BL-P4-001 | P4 | `extensions/credit_pipeline/workflows/{multi_agent_supervisor,code_interpreter_loop,rag_augmented_saga}.workflow.yaml` | 3 YAML workflow файла без runtime-loaders (только references в streamlit placeholder и feature_flag docs). `code_interpreter_loop` заявляет `e2b_execute` activity, нет реального исполнения. |

**Сводка: P0=2, P1=3, P2=4, P3=2, P4=1 (total=12).**

---

## Detailed evidence

### BL-P0-001: OSINT LLM failure returns prompt as report (fail-OPEN)

**Evidence (verify через `.venv/bin/python`):**

```python
# Mock LLM to fail
with patch('src.backend.core.ai.llm_gateway.get_litellm_gateway', side_effect=mock_get_litellm_gateway):
    result = await run_osint({'inn': '7707083893', 'company_name': 'Test'})
    # Output:
    #   raw_text starts with template? True
    #   raw_text len: 1015
    #   general_info (parsed from template): 'Полное наименование, ОГРН, дата регистрации, вид деятельности (2-4 предложения).'
```

**Path:** `extensions/osint_agent/functions/osint_workflow.py:333-334`

```python
except Exception:
    raw_text = prompt   # ← echoes the PROMPT template as the "report"
```

**Impact:** OSINT reports используются для due diligence. Когда LLM недоступен:
- `validate_report(prompt_template)` парсит template как будто это валидный отчёт
- `report["general_info"]` содержит template placeholder ("Полное наименование, ОГРН, дата регистрации, вид деятельности...")
- Downstream consumers получают отчёт, который **выглядит валидно**, но не содержит реальных данных
- Audit trail потерян — нет отличия "реальный отчёт с пустыми данными" от "LLM down"

**Минимальная рекомендация:** Fail-CLOSED — поднять доменный exception (`OSINTLLMUnavailableError`) или вернуть `report["status"]="unavailable", report["error"]="llm_unavailable"`. Шаблон не должен попадать в `raw_text`. Добавить `audit_event("osint_llm_unavailable", severity="error")` через canonical facade.

**Тест-критерий:** `test_osint_workflow.py::TestRunOsint::test_llm_failure_returns_unavailable_status` — mock LLM raise, expect `result["status"] == "unavailable"` and `result["raw_text"] != prompt_template`.

---

### BL-P0-002: OSINT search failure → LLM hallucination (fail-OPEN)

**Evidence:**

```python
# Mock search to fail, LLM works
with patch(...search...FailingSearch().query raises ConnectionError):
    with patch(...llm...GoodGateway returns valid report):
        result = await run_osint({...})
        # Output:
        #   general_info: 'Real data here.'  ← HALLUCINATED
        #   result contains real LLM data: True
        #   result mentions Данные не найдены: False  ← NO indication of missing data
```

**Path:** `extensions/osint_agent/functions/osint_workflow.py:307-313`

```python
try:
    results_general = await _search_multi_provider(queries["general"])
    results_courts = await _search_multi_provider(queries["courts"])
    results_negative = await _search_multi_provider(queries["negative"])
except Exception:
    results_general = {"perplexity": None, "tavily": None, "scraped": []}  # ← empty, not error
    ...
```

**Impact:** Когда search service down, результаты = пустые. LLM получает prompt с `results_general="Данные не найдены"` placeholder, но всё равно генерирует **правдоподобный, но ложный** отчёт ("Real data here." в smoke). Это хуже чем BL-P0-001 — отчёт выглядит валидно, не упоминает "Данные не найдены", содержит **выдуманные** факты о компании. **Compliance/risk issue**: ложноположительный OSINT может привести к одобрению клиента с реальными проблемами.

**Минимальная рекомендация:** Добавить обязательный pre-condition check: если все 3 search providers вернули None/empty → raise `OSINTSearchUnavailableError` (или вернуть `status="insufficient_data"` + `missing_sources=["perplexity","tavily"]`). Не вызывать LLM без подтверждённых данных.

**Тест-критерий:** `test_osint_workflow.py::TestRunOsint::test_search_failure_does_not_invoke_llm` — mock search fails, mock LLM, verify LLM NOT called.

---

### BL-P1-001: orders_dsl uses non-existent `.then()` method

**Evidence:**

```python
# .venv/bin/python -c "from extensions.core_entities.orders.workflows.orders_dsl import build_all_order_workflows; build_all_order_workflows()"
# AttributeError: 'WorkflowBuilder' object has no attribute 'then'
```

**Path:** `extensions/core_entities/orders/workflows/orders_dsl.py:241,250,305,315,316,326,336`

```python
# Lines 241, 250 (poll_skb_result_workflow_spec):
.then(ActivityDeclaration(...))
.then(SensorDeclaration(...))

# Lines 305-336 (order_processing_workflow_spec):
.then(ActivityDeclaration(...))  # 5 occurrences
.then(SleepDeclaration(...))
```

**Actual WorkflowBuilder API** (per `src/backend/dsl/workflow/builder/sla_mixin.py:46-65` и `wait_mixin.py:33,70`):

- `.activity(name, *, args=..., timeout_s=..., retry_policy=..., output_key=...)` — atomic activity
- `.sleep(duration_s)` — durable sleep
- `.sensor(predicate, *, poll_interval_s=..., timeout_s=...)` — periodic sensor
- `.wait_for_signal(signal_name, *, ...)` — durable signal wait

**.then() НЕ существует ни в одном mixin.**

**Impact:**
- `poll_skb_result_workflow_spec()` (lines 217-258) и `order_processing_workflow_spec()` (lines 284-343) **crash** при вызове с `AttributeError`.
- `build_all_order_workflows()` (line 349-369) crashes на третьем workflow (`orders.poll_skb_result`).
- Все 3 saga-based workflows (`send_notification`, `create_skb_order`, `send_skb_result`) — OK (verified live).
- `build_all_order_workflows` нигде не вызывается из production code → **dead code с runtime crash**.
- Рискованно для будущего: любой wiring (lifecycle loader, migration script, тест) упадёт с непонятным AttributeError.

**Минимальная рекомендация:** Заменить `.then(<Decl>)` → `.activity(name=..., args={...})` для ActivityDeclaration; для SleepDeclaration/SensorDeclaration использовать соответствующие builder methods (`sleep()`, `sensor()`). Добавить тест `test_orders_dsl.py::test_all_workflow_specs_buildable` (отсутствует — нет coverage).

**Тест-критерий:** Smoke `from extensions.core_entities.orders.workflows.orders_dsl import build_all_order_workflows; assert len(build_all_order_workflows()) == 5`.

---

### BL-P1-002: TenantFacade.with_tenant kwargs mismatch (RESIDUAL cycle-3 T-08)

**Evidence:**

```python
# .venv/bin/python -c "asyncio.run(get_tenant_facade().with_tenant('tenant_42', principal_id='user_1'))"
# TypeError: CapabilityTenant.__init__() got an unexpected keyword argument 'tenant_id'
```

**Path:** `src/backend/services/tenancy/facade.py:116-119` (consumed by extensions via `src/backend.services.tenancy.facade.TenantFacade`).

```python
new_ctx = CapabilityTenant(
    tenant_id=tenant_id,      # ← WRONG: CapabilityTenant expects `id`
    principal_id=principal_id, # ← WRONG: CapabilityTenant expects `principal`
)
```

**Correct signature** (`src/backend/core/security/capabilities/tenant.py:36-54`):

```python
@dataclass(frozen=True, slots=True)
class CapabilityTenant:
    id: str
    principal: str
    scope_glob: str | None = None
```

**Impact:**
- `TenantFacade.with_tenant()` — официальный entry-point для scoped tenant operations (per docstring at line 95-111).
- При вызове в production: TypeError → tenant context не устанавливается → downstream capability checks fail closed.
- В цикле 3 это был deferred T-08 "TenantFacade kwargs fix" — **RESIDUAL** (комментарий в коде ссылается на S193 fix, но fix был применён к контракту, не к вызову).

**Минимальная рекомендация:** Заменить `CapabilityTenant(tenant_id=..., principal_id=...)` на `CapabilityTenant(id=tenant_id, principal=principal_id)` в `facade.py:116-119`. Добавить unit-test `test_tenant_facade.py::test_with_tenant_accepts_principal_id` (отсутствует).

**Тест-критерий:** `assert CapabilityTenant(id='tenant_42', principal='user_1').is_system is False` через `await facade.with_tenant('tenant_42', principal_id='user_1')`.

---

### BL-P1-003: validate_inn(None) raises TypeError instead of returning False

**Evidence:**

```python
# extensions/osint_agent/tests/test_osint_workflow.py:44-46
def test_none_inn(self) -> None:
    assert validate_inn(None) is False  # type: ignore[arg-type]
# FAILED: TypeError: expected string or bytes-like object, got 'NoneType'
```

**Path:** `src/backend/dsl/helpers/banking.py:31-43` (consumed by OSINT via `validate_inn`).

```python
def validate_inn(inn: str) -> bool:
    if _INN10.match(inn):  # ← TypeError on None
        ...
```

**Impact:** Контракт `validate_inn` — fail-CLOSED валидатор (per `osint_workflow.py:299-300` raise `ValueError` если invalid). Но при `None` вместо fail-CLOSED возврата `False` — exception propagation. Если какой-то caller (DSL helper, request schema) передаст `None` напрямую — неожиданный TypeError вместо штатного "invalid INN" rejection.

**Минимальная рекомендация:** Добавить guard в начало `validate_inn`:

```python
def validate_inn(inn: str | None) -> bool:
    if not isinstance(inn, str) or not inn:
        return False
    if _INN10.match(inn):
        ...
```

**Тест-критерий:** `assert validate_inn(None) is False` — тест уже существует (test_osint_workflow.py:46), просто code fix нужен.

---

### BL-P2-001: Dead SagaDeclaration import in orders_dsl.py

**Evidence:** AST analysis (см. команды ниже).

```
SagaDeclaration Name references: 0 (only in imports)
SagaDeclaration() instantiations: 0
SleepDeclaration Name references: 1
SleepDeclaration() instantiations: 1
SensorDeclaration Name references: 1
SensorDeclaration() instantiations: 1
```

**Path:** `extensions/core_entities/orders/workflows/orders_dsl.py:37`

```python
from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    SagaDeclaration,    # ← imported but NEVER used (saga() builder method constructs it)
    SensorDeclaration,
    SleepDeclaration,
    WorkflowDeclaration,
)
```

**Impact:** Cosmetic / dead code. SagaBuilder в `src/backend/dsl/workflow/builder/__init__.py:172-174` использует SagaDeclaration — но в orders_dsl импорт избыточен. Не сломано, но вводит в заблуждение читателя.

**Минимальная рекомендация:** Удалить `SagaDeclaration,` из импорта.

**Тест-критерий:** `ruff check --select F401` уже должен ловить (если включён). Verify `ruff check extensions/core_entities/orders/workflows/orders_dsl.py`.

---

### BL-P2-002: Invalid INN test data (TEST BUG, not code bug)

**Evidence:**

```python
# extensions/osint_agent/tests/test_osint_workflow.py:26
def test_valid_12_digit_inn(self) -> None:
    assert validate_inn("770708389307") is True
# FAILED: assert False is True
```

**Manual checksum verification:**

```
INN = 770708389307, digits: [7, 7, 0, 7, 0, 8, 3, 8, 9, 3, 0, 7]
products1 (10 weights): [49, 14, 0, 70, 0, 40, 27, 32, 54, 24]
sum1=310, check1=2, inn[10]=0, match=False  ← check digit 0 is wrong
products2 (11 weights): [21, 49, 0, 28, 0, 24, 15, 72, 36, 18, 0]
sum2=263, check2=0, inn[11]=7, match=False  ← check digit 7 is wrong
```

**Path:** `extensions/osint_agent/tests/test_osint_workflow.py:24-26`

**Impact:** `validate_inn("770708389307")` **корректно** возвращает `False` — checksum algorithm правильный, тестовые данные невалидны. Это TEST BUG, не code bug. Цикл 4 "зависнет" на этом тесте как failed, скрывая реальные баги.

**Минимальная рекомендация:** Заменить `"770708389307"` на валидный 12-digit ИНН (например, вычислить с правильной checksum) или удалить тест (test_invalid_inn_wrong_checksum уже покрывает invalid case).

**Тест-критерий:** `validate_inn(<valid_12_digit_inn>) is True` где <valid_12_digit_inn> проходит обе checksum проверки.

---

### BL-P2-003: credit_pipeline_v2 default inconsistency (RESIDUAL cycle-3 T-09)

**Evidence:**

```python
# src/backend/core/config/features/plugins.py:41-52
credit_pipeline_v2: bool = Field(
    default=True,   # ← actual default
    title="T3 S7: credit_pipeline plugin (SKB/НБКИ) — V11 layout",
    description=(
        "Sprint 7 Team T3. Owner: T3. ... "
        "default-OFF до завершения миграции (Sprint 8 flip ON)."  # ← contradicts default
    ),
)
```

```python
# extensions/credit_pipeline/tests/test_credit_pipeline_v2_flag.py:15-17
def test_credit_pipeline_v2_flag_exists_and_default_off() -> None:
    assert get_feature_flag_service().is_enabled("credit_pipeline_v2") is False
# FAILED: assert True is False
```

```python
# tests/unit/core/config/test_features_plugins.py:17-18
flags = PluginsFlags()
for f in ("extensions_credit_workflow", "credit_pipeline_v2"):
    assert getattr(flags, f) is True, f"{f} default не False"  # ← expects default True
```

**Path:** `src/backend/core/config/features/plugins.py:41`

**Impact:**
- Description говорит "default-OFF", но `default=True`.
- 2 test files имеют **противоречивые** expectations (1 expects default-OFF, 1 expects default-ON).
- Текущее реальное поведение: V11 migration **active by default** (per `default=True`).
- Если description правдив (миграция не завершена) — текущий default опасен (legacy shim path не используется → несовместимое поведение).
- Если default правдив (миграция завершена) — описание вводит в заблуждение.

**Минимальная рекомендация:** Согласовать default с description: либо `default=False` + flip ON через env / admin API, либо обновить description ("default-ON с Sprint 8"). Согласовать оба теста.

**Тест-критерий:** `get_feature_flag_service().is_enabled("credit_pipeline_v2")` consistent across all test files + description matches actual.

---

### BL-P2-004: Silent ES indexing failures (legitimate but no observability)

**Evidence:**

```python
# extensions/core_entities/orders/services/orders.py:108-113
def _index_order_async(self, instance: Any) -> None:
    if instance is None:
        return
    try:
        from src.backend.core.io.indexers import get_order_indexer
        get_order_indexer().index_one_fire_and_forget(instance)
    except Exception:  # noqa: BLE001
        return  # ← silent failure
```

**Path:** `extensions/core_entities/orders/services/orders.py:112-113,125-126`

**Impact:** ES indexing failures (search index рассинхронизирован с БД) **не observability-detectable**. Per S168 pattern это намеренный fire-and-forget (комментарий: "ES-сбой не должен ломать commit заказа"), но даже `logger.warning` отсутствует — полная тишина.

**Минимальная рекомендация:** Заменить `return` на `logger.warning("order_indexer_failed", extra={"order_id": ...})` хотя бы в debug-режиме. Не блокировать commit, но логировать.

**Тест-критерий:** При ES outage — verify в logs есть warning events.

---

### BL-P3-001: Broad `except Exception` в OSINT workflow

**Evidence:** 5× locations (см. BL-P3-001 в findings table).

**Path:** `extensions/osint_agent/functions/osint_workflow.py:239,264,275,310,333`

**Impact:** OSINT workflow устойчив к внешним сбоям (graceful degradation), но broad except скрывает programming errors. Уместно для outer try/except в graceful-degradation pattern, но не для всех 5 случаев.

**Минимальная рекомендация:** Раздробить: `httpx.HTTPError` для `_scrape_url`, конкретные исключения для LLM/search. Избегать `except Exception` без re-raise.

**Тест-критерий:** `mypy --strict` — broad except без re-raise warning.

---

### BL-P3-002: `except Exception: pass` в credit audit emission

**Evidence:**

```python
# extensions/credit_pipeline/agents/__init__.py:101-103
try:
    await emit_audit_safe(...)
except Exception:
    # Audit emission не должен блокировать scoring decision.
    pass  # ← NO logging
```

**Path:** `extensions/credit_pipeline/agents/__init__.py:101-103`

**Impact:** Audit failures silently swallowed. Audit events — критичны для compliance (PII, GDPR, banking regulation). Потеря audit event для `credit_rejected` (unknown_tenant) = regulatory gap.

**Минимальная рекомендация:** Хотя бы `logger.warning("audit_emit_failed", exc_info=True)` — observability без блокировки scoring.

**Тест-критерий:** Mock emit_audit_safe to raise → verify logger.warning called.

---

### BL-P4-001: 3 workflow YAML без runtime-loaders

**Evidence:**

- `extensions/credit_pipeline/workflows/multi_agent_supervisor.workflow.yaml`
- `extensions/credit_pipeline/workflows/code_interpreter_loop.workflow.yaml`
- `extensions/credit_pipeline/workflows/rag_augmented_saga.workflow.yaml`

**Path:** extensions/credit_pipeline/workflows/

**Impact:** Файлы есть, парсятся (4 steps для rag, 6 для code_interpreter, 7 для multi_agent — verified), но runtime loaders отсутствуют. `multi_agent_supervisor_enabled` feature_flag default-OFF, `code_interpreter_loop` ссылается на `services.ai.e2b_execute` (нет в коде — `src/backend/services/ai/multi_agent/supervisor.py:25` flag default-OFF).

**Минимальная рекомендация:** Решить архитектурно — либо удалить (dead demo), либо добавить registry-based loader (`extensions/credit_pipeline/workflows/__init__.py` пустой, кроме TODO). Per Ponytail: deletion over addition.

**Тест-критерий:** N/A (это решение, не bug).

---

## Cycle-1+2+3 residuals (verified/mutated/resolved)

| ID | Status | Evidence |
|---|---|---|
| T-1.1 composition root fix | **RESOLVED** | `src/backend/plugins/composition/workflow_setup.py:1-83` — `_bootstrap_default_declarations` удалена (commit 898c4b93). Default-OFF флаг WORKFLOW_BOOTSTRAP_DEFAULTS_ENABLED убран. `tools/checks/check_workflows_extensions.py` exit 0. |
| T-1.2 SSE/HITL auth (8 xfailed tests) | не проверено | вне scope данного аудита (security domain). |
| T-1.3 MQ DLQ data-loss | не проверено | вне scope (infrastructure/messaging domain). |
| T-1.4 multicast | **RESOLVED** (per BASELINE) | T-1.4 в HEAD 22e08a0d. Не перепроверял (вне scope). |
| T-1.5 policy_mixin / gateway_adapter | **RESOLVED** (per BASELINE) | T-1.5 в HEAD. Не перепроверял. |
| T-2.1 reverse-layer cleanup | **RESOLVED** (per BASELINE) | T-2.1 в HEAD. Не перепроверял. |
| T-3.1 cachetools TTLCache+asyncio.Lock | **RESOLVED** (per BASELINE) | T-3.1 в HEAD. Не перепроверял. |
| T-4.1 text-RAG E2E test | не проверено | вне scope. |
| T-W1-01 AuthenticationProviderUnavailableError import | **RESOLVED** (per BASELINE) | import OK (per smoke). |
| T-W1-02..07 | не проверено | workflow integration tests (вне scope, infra domain). |
| T-W1-08 credit scoring fail-closed | **RESOLVED + VERIFIED** | `extensions/credit_pipeline/agents/__init__.py:79-111` — unknown_tenant branch returns HIGH/score=0. Live test 4/4 PASS. |
| T-04 4-way CVE enforcement | не проверено | вне scope (security domain). |
| T-05 hardcoded shutdown timeout | не проверено | вне scope. |
| T-06 test-infra conftest | не проверено | вне scope. |
| T-08 TenantFacade kwargs fix | **RESIDUAL** | `src/backend/services/tenancy/facade.py:116-119` — `CapabilityTenant(tenant_id=, principal_id=)` некорректные kwargs → TypeError. **См. BL-P1-002.** |
| T-09 credit_pipeline_v2 default consistency | **RESIDUAL** | `src/backend/core/config/features/plugins.py:41` — `default=True`, description says "default-OFF", test expects default-OFF. **См. BL-P2-003.** |
| T-10 defusedxml drop-in | **RESOLVED** (per BASELINE) | `src/backend/dsl/engine/processors/eip/marshal/formats.py:23,128-133` — defusedxml preferred, guarded try/except. |
| T-11 organic feature | не проверено | вне scope. |

**Сводка residuals (перепроверено):**

- T-W1-08 RESOLVED (verified live, fail-CLOSED confirmed)
- T-08 RESIDUAL (TenantFacade kwargs mismatch — BL-P1-002)
- T-09 RESIDUAL (credit_pipeline_v2 default = True — BL-P2-003)
- T-1.1 RESOLVED (composition root crash fix verified)

---

## Contradictions/overlaps to flag

1. **Контрадикторные тесты для `credit_pipeline_v2`:** extensions test expects default-OFF, src test expects default-ON. См. BL-P2-003.

2. **Dead code overlap с BL-P1-001:** `orders_dsl.py:37` SagaDeclaration dead import — minor, но связан с основным багом `.then()`. Можно фиксить одним PR.

3. **OSINT fail-OPEN (BL-P0-001 + BL-P0-002):** Оба связаны с одним корнем — отсутствие fail-CLOSED contract для LLM/search failures. Можно фиксить одним design review + 2 unit tests.

4. **Существующие vs новые broad except:** OSINT (BL-P3-001) vs orders service (BL-P2-004) vs scoring_agent (BL-P3-002) — все 3 silent-failure patterns, разные приоритеты (P3 vs P2 vs P3). Не пересекаются по fix.

5. **Domain overlap:** `validate_inn` (BL-P1-003) находится в `src/backend/dsl/helpers/banking.py`, но consumer — OSINT extension. Это cross-cutting (banking helper для OSINT). Фикс в core, тест в extension.

---

## Readiness score 0–100 с формулой и обоснованием

**Формула:**

```
Readiness = Base × (1 - P0_penalty) × (1 - P1_penalty) × (1 - P2_penalty) × TestCoverage_factor
```

**Base = 100.**

**Penalties:**

- P0 (security/data-loss/race/fail-open) → -25 per finding, max -50
- P1 (layer boundaries, dead code that breaks runtime) → -10 per finding, max -30
- P2 (dead code, library replacement) → -3 per finding, max -15

**TestCoverage_factor** = `passed / (passed + failed)` для extensions tests.

**Расчёт:**

- P0 findings: 2 (BL-P0-001, BL-P0-002) → penalty = min(2×25, 50) = 50
- P1 findings: 3 (BL-P1-001, BL-P1-002, BL-P1-003) → penalty = min(3×10, 30) = 30
- P2 findings: 4 (BL-P2-001..004) → penalty = min(4×3, 15) = 12
- TestCoverage_factor = 83 / (83 + 3) = 0.965

**Penalty multipliers (произведение):**

```
After P0: 100 × (1 - 0.50) = 50
After P1: 50 × (1 - 0.30) = 35
After P2: 35 × (1 - 0.12) = 30.8
Apply coverage: 30.8 × 0.965 = 29.7
```

**Округлено: Readiness = 30/100.**

**Обоснование:**

- 2 P0 finding (fail-OPEN OSINT) блокируют production-ready status. OSINT reports используются для due diligence banking — hallucinated/template-as-report это **active compliance risk**.
- 3 P1 finding — `orders_dsl.py` runtime crash (`AttributeError`), `TenantFacade.with_tenant` kwarg bug (fail-OPEN для tenant isolation), `validate_inn(None)` TypeError (fail-OPEN potential). Эти баги не блокируют startup, но ломают критичные пути при первом использовании.
- 4 P2 finding — мёртвый импорт SagaDeclaration, невалидный тестовый ИНН, feature flag inconsistency, silent ES failures. Каждое само по себе косметическое, но в совокупности индикатор regression.
- Test coverage: 83/86 (96.5%) — относительно высокий, но 3 failed теста (test_credit_pipeline_v2_flag, test_valid_12_digit_inn, test_none_inn) — это regressions которые НЕ ДОЛЖНЫ быть в HEAD после 22e08a0d reapply.

**Readiness < 80 блокирует promotion to production** (per условию задачи).

**Verdict: NOT READY for production.**

---

## Recommended next tasks

По приоритету (P0 → P4):

1. **BL-P0-001 (OSINT LLM fail-OPEN)** — Sprint-blocker.
   - Replace `raw_text = prompt` (line 334) with `raise OSINTLLMUnavailableError` or return structured `status="unavailable"`.
   - Add `audit_event("osint_llm_unavailable", severity="error")` через canonical facade.
   - Add test `test_osint_workflow.py::TestRunOsint::test_llm_failure_returns_unavailable_status`.

2. **BL-P0-002 (OSINT search fail-OPEN / LLM hallucination)** — Sprint-blocker.
   - In `run_osint` (lines 307-313), if all 3 search providers return None/empty → return `status="insufficient_data"` BEFORE invoking LLM.
   - Add test `test_osint_workflow.py::TestRunOsint::test_search_failure_returns_insufficient_data_without_llm_call`.

3. **BL-P1-001 (orders_dsl `.then()` bug)** — Critical-path runtime crash.
   - Replace `.then(<Decl>)` calls in `orders_dsl.py` (7 occurrences) with `.activity()` / `.sleep()` / `.sensor()` per builder API.
   - Add test `test_orders_dsl.py::test_all_workflow_specs_buildable` (новый файл, нет coverage).

4. **BL-P1-002 (TenantFacade kwargs)** — Cycle-3 T-08 RESIDUAL.
   - Fix `src/backend/services/tenancy/facade.py:116-119`: `CapabilityTenant(id=tenant_id, principal=principal_id)`.
   - Add test `test_tenant_facade.py::test_with_tenant_accepts_principal_id` (отсутствует в extensions scope, требует src/ test).

5. **BL-P1-003 (validate_inn None)** — small fail-OPEN.
   - Add guard `if not isinstance(inn, str) or not inn: return False` в `banking.py:31-43`.
   - Existing test `test_none_inn` (osint_workflow.py:46) will PASS после fix.

6. **BL-P2-003 (credit_pipeline_v2 default)** — Cycle-3 T-09 RESIDUAL.
   - Either: change `default=True` → `default=False` (consistent with description), update `test_features_plugins.py:18` to expect default-OFF.
   - Or: update description to "default-ON since Sprint 8 completion".

7. **BL-P2-001, BL-P2-002, BL-P2-004** — non-blocking cleanup.

8. **BL-P3-001, BL-P3-002, BL-P4-001** — defer to cleanup sprint.

**Effort estimate:** 2-3 dev-days для всех P0+P1 (5 critical fixes), 1 dev-day для P2+P3 (cleanup).

---

## Commands run (с явным указанием Python interpreter)

```bash
# All runtime checks через .venv/bin/python (per BASELINE.md instruction)
.venv/bin/python -c "import asyncio; from extensions.credit_pipeline.agents import scoring_agent; ..."  # T-W1-08 verification (4/4 PASS)
.venv/bin/python -m pytest extensions/credit_pipeline/tests/ -v --tb=short   # 33 passed, 1 failed (test_credit_pipeline_v2_flag)
.venv/bin/python -m pytest extensions/core_entities/ -v --tb=short         # 35 passed, 0 failed
.venv/bin/python -m pytest extensions/osint_agent/ extensions/core_admin/ -v --tb=short   # 15 passed, 2 failed (test_valid_12_digit_inn, test_none_inn)
.venv/bin/python -m pytest extensions/dadata/ extensions/skb/ extensions/test_plug/ -v --tb=short   # 0 tests (schemas-only)
.venv/bin/python -m pytest extensions/ -v --tb=short   # 83 passed, 3 failed total
.venv/bin/python -c "import sys; sys.path.insert(0, '/home/user/dev/gd_integration_tools'); ..."  # OSINT fail-OPEN verification (2 scenarios)
.venv/bin/python -c "from src.backend.core.config.features.plugins import PluginsFlags; print(PluginsFlags().credit_pipeline_v2)"   # T-09 verification: True
.venv/bin/python -c "from extensions.core_entities.orders.workflows.orders_dsl import build_all_order_workflows; ..."   # BL-P1-001 verification: AttributeError
.venv/bin/python -c "import asyncio; from src.backend.services.tenancy.facade import get_tenant_facade; asyncio.run(get_tenant_facade().with_tenant('tenant_42', principal_id='user_1'))"   # BL-P1-002 verification: TypeError
.venv/bin/python -c "from src.backend.dsl.helpers.banking import validate_inn; validate_inn(None)"   # BL-P1-003 verification: TypeError
.venv/bin/python -c "from src.backend.dsl.workflow.builder import WorkflowBuilder; print(sorted(m for m in dir(WorkflowBuilder) if not m.startswith('_')))"   # Verify .then() doesn't exist
.venv/bin/python -c "import ast; from pathlib import Path; ...AST analysis of orders_dsl.py"   # BL-P2-001 verification: SagaDeclaration dead import
.venv/bin/python tools/checks/check_workflows_extensions.py   # Layer boundaries gate: OK (exit 0)
.venv/bin/python -m pytest tests/unit/core/api/test_api_facade_contract.py -v --tb=short   # 9 passed (contract test for orders_dsl/osint_workflow)
```

**Не выполнено (по условию задачи):**

- `git commit`, `git push` — запрещены.
- `pip install`, `poetry add` — запрещены.
- Изменения в source/configs/lockfiles — запрещены.
- Чтение cycle-1/2/3 markdown, KNOWN_ISSUES.md, CLAUDE.md, PLAN.md, DEEP_AUDIT_REPORT.md, triage_allowlist_report.md — запрещены.

---

## Краткая сводка для parent agent

- **Статус:** NOT READY for production (P0 + P1 findings present).
- **Readiness:** 30/100.
- **P0:** 2 (OSINT fail-OPEN × 2).
- **P1:** 3 (orders_dsl runtime crash, TenantFacade kwargs, validate_inn None).
- **P2:** 4 (SagaDeclaration dead, test data invalid, flag inconsistency, silent ES).
- **P3:** 2 (broad except OSINT, silent audit swallow).
- **P4:** 1 (3 YAML workflows без loaders).
- **Total:** 12 findings, 5 critical (P0+P1).
- **Output report:** `docs/audit/swarm-2026-08-06/cycle-4/phase-1/10-business-logic.md`.
- **Critical blockers для parent:**
  - **BL-P0-001** (OSINT LLM fail-OPEN, line 333-334) — compliance risk.
  - **BL-P0-002** (OSINT search fail-OPEN, line 307-313) — hallucinated reports.
  - **BL-P1-001** (orders_dsl `.then()` AttributeError, line 241+) — runtime crash on `build_all_order_workflows()`.
  - **BL-P1-002** (TenantFacade kwargs mismatch, src/backend/services/tenancy/facade.py:116) — tenant isolation fail-OPEN.
- **Cycle-3 residuals:** T-08 RESIDUAL (BL-P1-002), T-09 RESIDUAL (BL-P2-003). T-1.1 RESOLVED. T-W1-08 RESOLVED + VERIFIED.
- **Test pass rate:** 83/86 = 96.5% (3 pre-existing failures, not introduced by this audit).