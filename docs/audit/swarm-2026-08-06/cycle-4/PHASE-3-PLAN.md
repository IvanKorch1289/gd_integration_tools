# Cycle 4 / Phase 3 — План доработки

> **Дата:** 2026-08-07
> **HEAD:** `22e08a0d` (cycle-1/2/3 reapply commit)
> **Scope:** минимальный набор правок по итогам PHASE-2-SUMMARY.md (172 findings)
> **Запрещено:** менять source/lockfile/allowlist/s3.py/blue_green; 8 правок cycle 1+2+3 в HEAD не переписывать; pre-existing residual `services/ai/gateway_adapter.py:128-129` не трогать
> **Критично:** T-08 TenantFacade kwargs fix = critical path (1 строка) + regression test
> **Метод:** атомарные PR-ы по workstream, docstring-marker `cycle-4/D-AUDIT-NNN`, baseline-инварианты сохраняются

---

## 0. Базовые инварианты и gates

### 0.1 Baseline-инварианты (НЕ должны дрейфовать)

| Инвариант | Текущее значение | Контроль |
|---|---|---|
| Layer checker | `python tools/check_layers.py --root src` → 175 legacy / **0 new** | `make lint` + ручной прогон |
| Security allowlist | 27 active CVE-IDs | `grep -cE "^CVE-\|^GHSA-\|^PYSEC-" .security/pip-audit-allowlist.txt` |
| Docstring gate | 0 missing (838 files) | `make check-docstrings MAX_ALLOWED=0` |
| Streamlit pin | `streamlit>=1.58.0,<2.0.0` (`pyproject.toml:137`) | `grep` pin |
| `uv.lock` churn | ±0 строк | `git diff uv.lock \| wc -l` (должен быть 0) |
| Smoke-тесты | 8/8 PASS (см. BASELINE.md §Smoke-тесты) | `.venv/bin/python -m pytest <smoke-paths>` |

### 0.2 Запреты (Phase 3 contract)

1. **НЕ переписывать** 8 правок cycle 1+2+3 (T-1.4, T-1.5, T-3.1, T-W1-01, T-W1-05, T-W1-08, T-02, T-03) — уже в HEAD 22e08a0d.
2. **НЕ удалять** `except Exception` без concrete handling в том же коммите (re-raise / DLQ-write / AuditEvent / quarantine).
3. **НЕ растить** allowlist 27→N (`tools/pip_audit_gate.py` + `.security/pip-audit-allowlist.txt`).
4. **НЕ трогать** pre-existing residual `services/ai/gateway_adapter.py:128-129` (`except Exception: pass` — cycle-1 critic flagged, cycle-2/3/4 plans явно НЕ переписывать).
5. **НЕ менять** `pyproject.toml` cross-pin duplicates (`streamlit`/`lxml`/`pillow`) — P3-001 deferred, выходит за scope.
6. **НЕ менять** `uv.lock` / `.blue_green.state` / `dist/pip-audit.json` (pre-existing drift, не этому swarm).
7. **НЕ переводить** русские docstrings/comments в source — только добавлять маркер `cycle-4/D-AUDIT-NNN`.
8. **НЕ добавлять** новых runtime-зависимостей (`uv add`) без согласования.

### 0.3 Docstring marker scheme

Каждая атомарная правка помечает точку модификации docstring-комментарием `cycle-4/D-AUDIT-NNN` (NNN = 100..199 для Phase 3, чтобы не конфликтовать с D-AUDIT-02/03/11/95 циклов 1-3).

Формат:
```python
# cycle-4/D-AUDIT-NNN — <краткое описание fix>
```

---

## 1. Разрешение противоречий (C-1..C-5)

> Phase 2 зафиксировал 5 contradictions + 5 convergence (всего 10 секций §5). Явное разрешение для архитектурно-критичных:

| ID | Противоречие / Конвергенция | Где разрешается | Статус |
|---|---|---|---|
| **C-1** | T-08 TenantFacade kwargs (RESIDUAL + MUTATED, 2 домена) | Wave 1 → **T-W1-01** | **RESOLVED in Phase 3** (1 строка + test) |
| **C-2** | defusedxml drop-in неполный (2 точки: SAML dev-mode + XmlDataFormat fallback) | Wave 1 → **T-W1-04** | **RESOLVED in Phase 3** (delete try/except fallback) |
| **C-3** | PickleDataFormat RCE — DSL-only blind spot для security | Wave 1 → **T-W1-05c** | **RESOLVED in Phase 3** (delete + CapabilityPolicy deny) |
| **C-4** | PII fail-OPEN convergence (DSL + RAG + Security, разные модули) | Wave 1 → **T-W1-09** | **RESOLVED in Phase 3** (centralized `pii.fail_closed = True` + AuditEvent) |
| **C-5** | DLQ wiring: CDC RESOLVED vs MQ RESIDUAL (apparent contradiction, разные subsystems) | Wave 1 → **T-W1-08** | **PARTIAL** (CDC подтверждён RESOLVED; MQ через Phase 3 fix) |
| C-6 | HITL auth convergence (API + Entrypoints) | Wave 2 → **T-W2-01** | RESOLVED in Phase 3 |
| C-7 | Temporal Worker lifecycle (workflow P0-002 + cancel fail-OPEN) | Wave N → **N-1** | DEFERRED to cycle 5+ (HIGH risk, ADR-зависимо) |
| C-8 | `credit_pipeline_v2` default inconsistency (test vs description) | Wave N → **N-8** | DEFERRED to cycle 5+ (test-fixture fix) |
| C-9 | Security `validate_sql drop` re-discovered как Phase-1 P0 | Wave 1 → **T-W1-03** | **RESOLVED in Phase 3** (cross-domain, единый fix) |
| C-10 | B-17 (CDC) vs Temporal lifecycle (different subsystems) | ADR-level → **N-1** | DEFERRED (требует ADR-level решения) |

**Итог:** 5/5 contradictions C-1..C-5 разрешаются в Wave 1 (одна critical, 4 P0 fix). C-6/C-9 — Wave 2/Cross. C-7/C-8/C-10 — deferred.

---

## 2. Wave 0 — Developer preflight (1 задача)

### T-W0-01 — Phase-3 preflight gate

| Поле | Значение |
|---|---|
| Global task ID | `T-W0-01` |
| Docstring marker | `cycle-4/D-AUDIT-100` |
| Приоритет | P0 (блокер всех downstream-волн) |
| Домены | cross-cutting (security/infra/DSL/workflow) |
| Finding IDs | — (re-verification, не finding) |
| Пути файлов | `tools/check_layers.py`, `tools/pip_audit_gate.py`, `tools/cycle-1-preflight.sh`, `tools/check_docstrings.py`, `.security/pip-audit-allowlist.txt`, `Makefile` |
| Зависимости | — (root) |
| Параллельность | serial (блокирует Wave 1) |
| LOC range | 0 (read-only) |
| Rollback risk | none (не мутирует код) |

**Минимальный diff:** нет (read-only verification). Прогон всех baseline-checks + сохранение JSON-отчёта `docs/audit/swarm-2026-08-06/cycle-4/phase-3-preflight.json`.

**Критерий "готово":**
```bash
.venv/bin/python -m pytest \
  tests/unit/core/ai/test_gateway_adapter.py::test_smoke_baseline \
  tests/unit/services/tenancy/test_tenant_facade_smoke.py::test_set_tenant_idempotent \
  --tb=short -q
# → 2/2 PASS

.venv/bin/python tools/check_layers.py --root src    # → exit 0, 175/0
.venv/bin/python tools/check_docstrings.py           # → exit 0, 0 missing
make audit-deps                                      # → 27 allowlist, 0 new
grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt   # → 27
git diff --stat HEAD -- uv.lock                     # → 0 lines
```

**Read-only блок:**
- BASELINE.md → все 8 smoke-тестов PASS
- PHASE-2-SUMMARY.md → 172 findings cross-reference
- Docstring gate → 0
- Layer checker → 175/0
- Allowlist → 27
- uv.lock → 0 churn

---

## 3. Wave 1 — P0 security/reliability (9 локальных задач)

> Все P0 из PHASE-2 §3.1 + cross-domain конвергенции C-1/C-2/C-3/C-4. Атомарный fix = один коммит. Минимальные LOC. Все runtime-тесты через `.venv/bin/python -m pytest`. Запрет удалять `except Exception` без concrete handling.

### 3.1 Параллельные группы Wave 1

```
┌─ Группа A (critical path, 1 коммит) ─────────────────┐
│  T-W1-01: T-08 TenantFacade kwargs re-fix            │
└──────────────────────────────────────────────────────┘
                       ↓
┌─ Группа B (security RCE-tier, 4 параллельных PR) ────┐
│  T-W1-02: SAML impersonation guard                   │
│  T-W1-03: per-workflow SQL policy context            │
│  T-W1-04: defusedxml drop-in (SAML + XmlDataFormat)  │
│  T-W1-05: RCE triple-fix (admin_cron + Script + Pickle) │
└──────────────────────────────────────────────────────┘
                       ↓
┌─ Группа C (data-loss + fail-CLOSED, 3 параллельных PR) ─┐
│  T-W1-06: OSINT fail-OPEN                                 │
│  T-W1-07: AdminService fail-CLOSED at gateway=None       │
│  T-W1-08: MQ consumer DLQ wiring                          │
│  T-W1-09: PII fail-CLOSED contract (DSL + RAG)            │
└──────────────────────────────────────────────────────────┘
```

Группы B и C — параллельны между собой. Внутри каждой группы — также параллельны (нет shared file edits).

---

### T-W1-01 — T-08 TenantFacade kwargs re-fix [CRITICAL PATH]

| Поле | Значение |
|---|---|
| Global task ID | `T-W1-01` |
| Docstring marker | `cycle-4/D-AUDIT-101` |
| Приоритет | **P0 critical path** |
| Домены | services (03) + business-logic (10) — 2 домена подтверждают RESIDUAL |
| Finding IDs | `services:SERV-P0-001` + `business-logic:BL-P1-002` + `cycle-3:T-08 RESIDUAL + MUTATED` + C-1 |
| Пути файлов | `src/backend/services/tenancy/facade.py:96-124` (target: ~line 116-119) + новый test `tests/unit/services/tenancy/test_tenant_facade_kwargs.py` |
| Зависимости | T-W0-01 |
| Параллельность | **serial** (блокирует Wave 2 multi-tenant tests) |
| LOC range | +1 source / +30 test (1 строка fix + regression test) |
| Rollback risk | low (1 строка; reverting возвращает cycle-3 broken state) |

**Минимальный diff (1 строка):**
```python
# До (cycle-3 S193 — BROKEN):
return CapabilityTenant(tenant_id=tenant_id, principal_id=principal_id)

# После (cycle-4/D-AUDIT-101):
return CapabilityTenant(id=tenant_id, principal=principal_id)
```

**Regression test (NEW, без mock на `set_tenant`):**
```python
# tests/unit/services/tenancy/test_tenant_facade_kwargs.py
async def test_with_tenant_accepts_principal_id_kwarg():
    """cycle-4/D-AUDIT-101: regression on T-08 kwargs re-fix."""
    facade = TenantFacade()
    ctx = await facade.with_tenant(
        tenant_id="t-001",
        principal_id="p-007",
        permissions=frozenset({"read"}),
    )
    assert ctx.tenant.id == "t-001"
    assert ctx.principal.id == "p-007"
```

**Критерий "готово":**
```bash
.venv/bin/python -m pytest \
  tests/unit/services/tenancy/test_tenant_facade_kwargs.py \
  tests/unit/services/tenancy/ \
  --tb=short -q
# → green, новый test PASS, никаких regressions
```

**Гарантии:**
- ✅ 1 source LOC
- ✅ 1 new test file (~30 LOC)
- ✅ Не трогает `set_tenant` mock-логику (test пройдёт на production path)
- ✅ Cycle-3 broken fix заменён на правильный kwarg names (`id=`/`principal=` per `CapabilityTenant.__init__` signature)

---

### T-W1-02 — SAML impersonation guard

| Поле | Значение |
|---|---|
| Global task ID | `T-W1-02` |
| Docstring marker | `cycle-4/D-AUDIT-102` |
| Приоритет | P0 (Tier 1A — auth bypass) |
| Домены | security (02) |
| Finding IDs | `security:SECURITY-P0-001` + `cycle-1:SAML impersonation carry-over` |
| Пути файлов | `src/backend/core/auth/auth_selector.py:147-167` (`_verify_saml`) + новый test `tests/unit/core/auth/test_saml_impersonation.py` |
| Зависимости | T-W0-01 |
| Параллельность | parallel с T-W1-03/04/05 |
| LOC range | +5 source (raise on missing token signature) / +25 test |
| Rollback risk | low (security guard; reverting восстанавливает cycle-1 broken state) |

**Минимальный diff:** добавить проверку подписи SAML token перед чтением cookie/header. Конкретно: если `_verify_saml` принимает cookie напрямую без проверки `RelayState`/`Signature`, добавить `raise SAMLImpersonationError` при отсутствии `request.signature` или при несоответствии `assertion.subject`.

**Критерий "готово":**
```bash
.venv/bin/python -m pytest \
  tests/unit/core/auth/test_saml_impersonation.py \
  tests/unit/core/auth/ \
  --tb=short -q
```

---

### T-W1-03 — Per-workflow SQL policy context propagation

| Поле | Значение |
|---|---|
| Global task ID | `T-W1-03` |
| Docstring marker | `cycle-4/D-AUDIT-103` |
| Приоритет | P0 (Tier 1A — policy silently dropped) |
| Домены | security (02) |
| Finding IDs | `security:SECURITY-P0-002` + `cycle-1:validate_sql drop RESIDUAL` + C-9 (convergence) |
| Пути файлов | `src/backend/services/agent_security/facade.py:121-133` (`validate_sql` signature) |
| Зависимости | T-W0-01 |
| Параллельность | parallel с T-W1-02/04/05 |
| LOC range | +8 source (add `context=` param + plumb through) / +20 test |
| Rollback risk | low (extending signature, not breaking) |

**Минимальный diff:** расширить `validate_sql(*, context: SqlPolicyContext)` — `context` обязан содержать `tenant_id` + `workflow_id` + `principal_id`. Вызовы без `context` → `AgentSecurityContextRequiredError`. Существующие callers — обновить, добавив context (≤10 callsites).

**Критерий "готово":**
```bash
.venv/bin/python -m pytest \
  tests/unit/services/agent_security/test_sql_policy_context.py \
  tests/unit/services/agent_security/ \
  --tb=short -q
```

---

### T-W1-04 — defusedxml drop-in (SAML + XmlDataFormat)

| Поле | Значение |
|---|---|
| Global task ID | `T-W1-04` |
| Docstring marker | `cycle-4/D-AUDIT-104` |
| Приоритет | P0 (Tier 1B — XXE/billion-laughs) |
| Домены | security (02) + DSL (06) |
| Finding IDs | `security:SECURITY-P0-003` + `dsl:DOMAIN-P0-001` + `cycle-3:T-10 deferred` + C-2 |
| Пути файлов | `src/backend/core/auth/facade.py:488-493` (SAML dev-mode verify) + `src/backend/dsl/engine/processors/eip/marshal/formats.py:91-140` (`XmlDataFormat.unmarshal`) |
| Зависимости | T-W0-01 |
| Параллельность | parallel с T-W1-02/03/05 |
| LOC range | -10 source (delete try/except stdlib fallback) / +5 source (hard import `defusedxml.ElementTree`) / +15 test |
| Rollback risk | low (`defusedxml` уже hard-imported в `bpmn_importer.py:55` и в `pyproject.toml`) |

**Минимальный diff:**
```python
# До (cycle-3 lazy fallback):
try:
    from defusedxml.ElementTree import fromstring as _et_fromstring
except ImportError:  # dev_light без defusedxml
    from xml.etree.ElementTree import fromstring as _et_fromstring  # XXE!

# После (cycle-4/D-AUDIT-104):
from defusedxml.ElementTree import fromstring as _et_fromstring  # noqa: F401
```

Удалить `try/except ImportError` блоки в обоих файлах. Если `defusedxml` отсутствует — fail-CLOSED `ImportError` at module load (НЕ silent fallback).

**Критерий "готово":**
```bash
.venv/bin/python -m pytest \
  tests/unit/core/auth/test_xml_parse.py \
  tests/unit/dsl/engine/processors/eip/marshal/test_xml_format.py \
  --tb=short -q
```

**Гарантии:**
- ✅ `defusedxml` уже в `uv.lock` (per `bpmn_importer.py:55` hard-import)
- ✅ Удаляем оба lazy fallback (SAML + DSL)
- ✅ Соответствует Ponytail-mode: «stdlib solution preferred over custom fallback» — заменяем fallback на единственный hard-import

---

### T-W1-05 — RCE triple-fix (admin_cron + ScriptRunner + PickleDataFormat)

| Поле | Значение |
|---|---|
| Global task ID | `T-W1-05` (3 коммита: T-W1-05a/b/c) |
| Docstring marker | `cycle-4/D-AUDIT-105a` / `105b` / `105c` |
| Приоритет | P0 (Tier 1A — RCE на production route) |
| Домены | API (05) + DSL (06) |
| Finding IDs | `api:DOMAIN-P0-002` + `dsl:DOMAIN-P0-002` + `dsl:DOMAIN-P0-003` + C-3 |
| Пути файлов | `src/backend/entrypoints/api/v1/endpoints/admin_cron.py:55-94,109-141` + `src/backend/dsl/engine/processors/script_runner.py:46-152` + `src/backend/dsl/engine/processors/eip/marshal/formats.py:236-272` |
| Зависимости | T-W0-01 |
| Параллельность | 3 под-задачи — каждая в отдельном коммите, разные файлы → **внутренний parallel OK** |
| LOC range | +20 source (whitelist + capability gate) / +40 test |
| Rollback risk | low (whitelist ограничивает surface; reverting восстанавливает RCE) |

**T-W1-05a — admin_cron importlib whitelist:**
```python
# До (cycle-3):
module = importlib.import_module(user_provided_module_name)

# После (cycle-4/D-AUDIT-105a):
_ALLOWED_CRON_MODULES = frozenset({
    "src.backend.infrastructure.scheduler.jobs.cleanup_dlq",
    "src.backend.infrastructure.scheduler.jobs.rotate_audit",
    # ... явно зафиксированный allowlist
})
if user_provided_module_name not in _ALLOWED_CRON_MODULES:
    raise CronModuleNotWhitelistedError(user_provided_module_name)
module = importlib.import_module(user_provided_module_name)
```

**T-W1-05b — ScriptRunner RCE:**
- Установить `allowed_languages: frozenset[str] = Field(default_factory=lambda: frozenset({"python"}))` (вместо `None`).
- Удалить `os.environ` copy в child process: `env=None` вместо `env=os.environ.copy()`.
- `CapabilityPolicy.require("dsl:script_runner:execute")` на входе.

**T-W1-05c — PickleDataFormat RCE:**
- Удалить `PickleDataFormat.unmarshal` (`pickle.loads(data)  # noqa: S301`).
- Заменить на `JsonDataFormat` или явный `MessagePackDataFormat` через registry.
- CapabilityPolicy deny-list: `dsl:format:pickle` → raise.

**Критерий "готово":**
```bash
.venv/bin/python -m pytest \
  tests/unit/entrypoints/api/v1/endpoints/test_admin_cron_whitelist.py \
  tests/unit/dsl/engine/processors/test_script_runner_capability.py \
  tests/unit/dsl/engine/processors/eip/marshal/test_pickle_removed.py \
  --tb=short -q
```

---

### T-W1-06 — OSINT fail-OPEN (LLM + search)

| Поле | Значение |
|---|---|
| Global task ID | `T-W1-06` |
| Docstring marker | `cycle-4/D-AUDIT-106` |
| Приоритет | P0 (Tier 1A — business-logic critical-path) |
| Домены | business-logic (10) |
| Finding IDs | `business-logic:BL-P0-001` + `business-logic:BL-P0-002` |
| Пути файлов | `extensions/osint_agent/functions/osint_workflow.py:307-313, 333-334` |
| Зависимости | T-W0-01 |
| Параллельность | parallel с T-W1-07/08/09 |
| LOC range | +12 source (raise domain exception + AuditEvent) / +15 test |
| Rollback risk | low (raising exception вместо silent echo) |

**Минимальный diff:**
```python
# До (BL-P0-002): raw_text = prompt
# До (BL-P0-001): raw_text = osint_result

# После (cycle-4/D-AUDIT-106):
if not osint_search_results:
    raise OSINTSearchUnavailableError(
        tenant_id=ctx.tenant.id,
        query=query,
        backend=backend_name,
    )
if not llm_response or llm_response.tool_calls is None:
    raise OSINTLLMUnavailableError(
        tenant_id=ctx.tenant.id,
        model=model_name,
    )
# AuditEvent("osint.fail_closed") emit перед raise
```

**Критерий "готово":**
```bash
.venv/bin/python -m pytest \
  extensions/osint_agent/tests/test_osint_fail_closed.py \
  --tb=short -q
```

---

### T-W1-07 — AdminService fail-CLOSED at gateway=None

| Поле | Значение |
|---|---|
| Global task ID | `T-W1-07` |
| Docstring marker | `cycle-4/D-AUDIT-107` |
| Приоритет | P0 (Tier 1A — admin authz bypass) |
| Домены | services (03) |
| Finding IDs | `services:SERV-P0-002` + `services:SERV-P1-003` (cross-ref: `_get_authz` swallows init exceptions) |
| Пути файлов | `src/backend/services/admin/api.py:58-80, 97-102` |
| Зависимости | T-W0-01 |
| Параллельность | parallel с T-W1-06/08/09 |
| LOC range | +8 source (raise + audit outcome) / +10 test |
| Rollback risk | low (security gate) |

**Минимальный diff:**
```python
# До (SERV-P0-002): _get_authz swallows all init exceptions
# До (SERV-P0-002 line 97-102): silent return None при gateway=None

# После (cycle-4/D-AUDIT-107):
def _get_authz(self) -> AuthorizationGateway:
    try:
        gw = self._authz_factory()
    except Exception as exc:
        raise AdminAuthorizationUnavailableError(...) from exc
    if gw is None:
        raise AdminAuthorizationUnavailableError("gateway is None")
    return gw
```

Audit `outcome="denied"` (НЕ `outcome="error"`) при security failure — resolves SERV-P1-004.

**Критерий "готово":**
```bash
.venv/bin/python -m pytest \
  tests/unit/services/admin/test_admin_fail_closed.py \
  --tb=short -q
```

---

### T-W1-08 — MQ consumer DLQ wiring

| Поле | Значение |
|---|---|
| Global task ID | `T-W1-08` |
| Docstring marker | `cycle-4/D-AUDIT-108` |
| Приоритет | P0 (Tier 1B — data-loss) |
| Домены | entrypoints (04) + services (03) cross-ref |
| Finding IDs | `entrypoints:ENTRY-P0-001` + `entrypoints:ENTRY-P0-002` + `cycle-1:T-1.3` + `cycle-2:T-W1-03` + C-5 (partial) |
| Пути файлов | `src/backend/entrypoints/stream/invoker_subscribers.py:57-93` + `src/backend/entrypoints/stream/subscribers.py:33,48` |
| Зависимости | T-W0-01 + T-W1-01 (для tenant context в DLQ payload) |
| Параллельность | parallel с T-W1-06/07/09 |
| LOC range | +30 source (dlq_writer + nack) / +25 test |
| Rollback risk | medium (изменение consumer semantics; требует интеграционного test) |

**Минимальный diff:**
```python
# До (cycle-1 bare except + log):
except Exception as exc:
    _logger.exception("invoker consumer failed")

# После (cycle-4/D-AUDIT-108):
except Exception as exc:
    await self._dlq_writer.write(
        topic=msg.topic,
        payload=msg.body,
        error=exc,
        tenant_id=ctx.tenant.id,
        attempts=msg.headers.get("x-attempt", 0),
    )
    await msg.ack()  # не requeue, чтобы не зациклиться; DLQ — источник правды
```

DI: добавить `dlq_writer` в `StreamSubscriber` через `app_state` singleton.

**Критерий "готово":**
```bash
.venv/bin/python -m pytest \
  tests/unit/entrypoints/stream/test_mq_dlq_wiring.py \
  --tb=short -q
```

**Гарантии:**
- ✅ `except Exception` НЕ удаляется, а **дополняется concrete handling** (DLQ-write + ack)
- ✅ Tenant context из T-W1-01 fix
- ✅ Соответствует C-5: CDC подтверждён RESOLVED (не трогаем); MQ через этот fix

---

### T-W1-09 — PII fail-CLOSED contract (DSL + RAG centralization)

| Поле | Значение |
|---|---|
| Global task ID | `T-W1-09` |
| Docstring marker | `cycle-4/D-AUDIT-109` |
| Приоритет | P0 (Tier 1B — PII fail-OPEN) |
| Домены | DSL (06) + RAG (09) + Security (02 cross-ref) |
| Finding IDs | `dsl:DOMAIN-P0-004` + `rag:DOMAIN-P0-002` + C-4 (convergence) |
| Пути файлов | `src/backend/dsl/engine/processors/security/pii_erase.py:139-228` + `src/backend/services/ai/rag_ingest_service.py:224-226` + новый модуль `src/backend/core/policy/pii_fail_closed.py` (≤50 LOC) |
| Зависимости | T-W0-01 + T-W1-01 (tenant context) |
| Параллельность | parallel с T-W1-06/07/08 |
| LOC range | +60 source (centralized contract + AuditEvent) / +30 test |
| Rollback risk | medium (изменение fail-OPEN → fail-CLOSED; downstream callers должны корректно обработать новый exception) |

**Минимальный diff:**
```python
# Новый модуль src/backend/core/policy/pii_fail_closed.py:
class PIIFailClosedContract:
    """cycle-4/D-AUDIT-109 — единый PII fail-CLOSED contract.

    Используется в pii_erase.py (DSL) и rag_ingest_service.py (RAG)
    для предотвращения silent PII leak при sanitizer failure.
    """

    fail_closed: bool = True  # global flag (default-ON для prod)

    def on_sanitizer_failure(self, *, tenant_id: str, source: str, exc: BaseException) -> None:
        if self.fail_closed:
            emit_audit_event("pii.sanitizer_failure", tenant_id=tenant_id, source=source, exc=repr(exc))
            raise PIIFailClosedError(source=source) from exc
        # fail-OPEN path (только для dev_light profile):
        _logger.warning("PII sanitizer failed (fail-OPEN active): %s", source)
```

В `pii_erase.py`:
```python
# До: except Exception: pass  (silent)
# После: contract.on_sanitizer_failure(...)
```

В `rag_ingest_service.py`:
```python
# До: except Exception: return content_text  (raw PII в vector store)
# После: contract.on_sanitizer_failure(...) → quarantine в отдельный индекс
```

**Критерий "готово":**
```bash
.venv/bin/python -m pytest \
  tests/unit/core/policy/test_pii_fail_closed_contract.py \
  tests/unit/dsl/engine/processors/security/test_pii_erase_fail_closed.py \
  tests/unit/services/ai/test_rag_ingest_quarantine.py \
  --tb=short -q
```

**Гарантии:**
- ✅ `except Exception` НЕ удаляется без concrete handling (дополняется `contract.on_sanitizer_failure`)
- ✅ Соответствует `Business Logic fail-CLOSED` pattern (per credit_pipeline T-W1-08)
- ✅ Quarantine queue для RAG ingest вместо raw PII в vector store

---

### 3.2 Wave 1 dependency matrix

| Task | Depends on | Blocks | Parallel-safe |
|---|---|---|---|
| T-W1-01 | T-W0-01 | T-W1-08/09 (tenant context) | serial first |
| T-W1-02 | T-W0-01 | — | yes |
| T-W1-03 | T-W0-01 | — | yes |
| T-W1-04 | T-W0-01 | — | yes |
| T-W1-05a/b/c | T-W0-01 | — | yes (different files) |
| T-W1-06 | T-W0-01 | — | yes |
| T-W1-07 | T-W0-01 | — | yes |
| T-W1-08 | T-W0-01, T-W1-01 | — | yes (post T-W1-01) |
| T-W1-09 | T-W0-01, T-W1-01 | — | yes (post T-W1-01) |

**Параллельные группы Wave 1 (макс. parallelism):**
- Группа 1: T-W1-01 (1 коммит, serial)
- Группа 2 (после T-W1-01): T-W1-02/03/04/05a/05b/05c/06/07 (8 параллельных коммитов)
- Группа 3 (после T-W1-01): T-W1-08/09 (2 параллельных коммита)

Итого: **11 коммитов** в Wave 1 (1 + 8 + 2), но **до 8 параллельных в Группе 2** если dev_team > 1.

---

## 4. Wave 2 — P1 layer track (3 задачи)

> Все P1 из PHASE-2 §3.2 в layer-категории. Фокус: восстановление cross-layer boundaries + HITL auth convergence.

### T-W2-01 — HITL + SSE principal/permissions propagation

| Поле | Значение |
|---|---|
| Global task ID | `T-W2-01` |
| Docstring marker | `cycle-4/D-AUDIT-120` |
| Приоритет | P1 (security convergence — C-6) |
| Домены | API (05) + Entrypoints (04) |
| Finding IDs | `api:DOMAIN-P0-001` + `entrypoints:ENTRY-P1-001` + `cycle-1:T-1.2` + `cycle-2:T-W1-07` + C-6 |
| Пути файлов | `src/backend/entrypoints/api/v1/endpoints/hitl.py:24-128` + `src/backend/services/workflows/hitl_service.py:178-355` + `src/backend/entrypoints/sse/handler.py:188-225` |
| Зависимости | T-W1-01 (для tenant_id) |
| Параллельность | parallel с T-W2-02/03 |
| LOC range | +25 source (router-level guard + tenant_id filter) / +20 test |
| Rollback risk | medium (security guard; reverting восстанавливает cross-tenant bypass) |

**Минимальный diff:**
- `hitl.py`: добавить `Depends(require_permission("hitl:approve"))` + `tenant_id: str = Path(...)`.
- `hitl_service.py`: добавить `assert ctx.tenant.id == hitl_request.tenant_id` filter.
- `sse/handler.py`: пробросить `principal=auth_ctx.principal, permissions=auth_ctx.permissions` в `dispatch_action_or_dsl`.

**Критерий "готово":**
```bash
.venv/bin/python -m pytest \
  tests/unit/entrypoints/api/v1/endpoints/test_hitl_guard.py \
  tests/unit/services/workflows/test_hitl_tenant_filter.py \
  tests/unit/entrypoints/sse/test_sse_principal_propagation.py \
  --tb=short -q
# → 8 ранее xfailed тестов теперь PASS
```

---

### T-W2-02 — Layer violations cleanup (DSL → infra/services)

| Поле | Значение |
|---|---|
| Global task ID | `T-W2-02` |
| Docstring marker | `cycle-4/D-AUDIT-121` |
| Приоритет | P1 (architecture) |
| Домены | DSL (06) + Services (03) |
| Finding IDs | `dsl:DOMAIN-P1-001` (CDCProcessor) + `dsl:DOMAIN-P1-005` (web.py) + `services:SERV-P1-002` (reverse-layer shims) |
| Пути файлы | `src/backend/dsl/engine/processors/external.py:1-100` (после `baf54d95`) + `src/backend/dsl/engine/processors/web.py:19-166` + `src/backend/services/io/files.py:1-20` + `src/backend/services/integrations/skb.py:127-152` |
| Зависимости | T-W0-01 |
| Параллельность | parallel с T-W2-01/03 |
| LOC range | +15 source (move CDCProcessor → extensions/dev_tools/) / -30 source (delete reverse-layer shims) / +10 test |
| Rollback risk | low (move code, не изменение logic) |

**Минимальный diff:**
- `external.py:CDCProcessor`: перенести в `extensions/dev_tools/cdc_processor.py` (per `baf54d95` cycle-4 baseline).
- `web.py`: удалить direct import `from src.backend.services.integrations.web_automation import ...` — заменить на CapabilityPolicy facade.
- `services/io/files.py` + `services/integrations/skb.py`: заменить reverse-layer shim на прямой импорт extension (YAGNI-mode одобряет).

**Критерий "готово":**
```bash
.venv/bin/python -m check_layers.py --root src    # → 175/0 (НЕ 176/0)
.venv/bin/python -m pytest \
  tests/unit/dsl/engine/processors/test_cdc_processor_moved.py \
  tests/unit/dsl/engine/processors/test_web_layer_boundary.py \
  --tb=short -q
```

---

### T-W2-03 — Webhook HMAC + admin_actions hardening

| Поле | Значение |
|---|---|
| Global task ID | `T-W2-03` |
| Docstring marker | `cycle-4/D-AUDIT-122` |
| Приоритет | P1 (fail-OPEN guards) |
| Домены | Entrypoints (04) + API (05) |
| Finding IDs | `entrypoints:ENTRY-P1-003` (webhook auth) + `entrypoints:ENTRY-P1-004` (HMAC fail-OPEN) + `api:DOMAIN-P1-003` (admin_actions mock-fallback) + `api:DOMAIN-P1-004` (admin_plugins mock-fallback) |
| Пути файлов | `src/backend/entrypoints/webhook/handler.py:84-127,155-169` + `src/backend/entrypoints/api/v1/endpoints/admin_actions.py:99-230` + `src/backend/entrypoints/api/v1/endpoints/admin_plugins.py:104-301` |
| Зависимости | T-W0-01 |
| Параллельность | parallel с T-W2-01/02 |
| LOC range | +30 source (raise on missing secret + registry-based dispatch) / +20 test |
| Rollback risk | medium (security gate; reverting восстанавливает bypass) |

**Минимальный diff:**
- `webhook/handler.py:155-169`: удалить `if secret: short-circuit` → always verify HMAC if subscription exists; raise `WebhookSignatureMissingError` otherwise.
- `webhook/handler.py:84-127`: `require_auth(method=AuthMethod.API_KEY)` (явно).
- `admin_actions.py:99-230`: удалить `_get_registry() → None → mock-fallback`; raise `AdminRegistryUnavailableError`.
- `admin_plugins.py:104-301`: удалить mock-fallback path; `CapabilityPolicy.require("admin:plugins:list")` на endpoint.

**Критерий "готово":**
```bash
.venv/bin/python -m pytest \
  tests/unit/entrypoints/webhook/test_hmac_fail_closed.py \
  tests/unit/entrypoints/api/v1/endpoints/test_admin_actions_no_mock_fallback.py \
  --tb=short -q
```

---

## 5. Wave 3 — P3 library replacement (1 задача)

### T-W3-01 — tenacity для RAG manual retry loop

| Поле | Значение |
|---|---|
| Global task ID | `T-W3-01` |
| Docstring marker | `cycle-4/D-AUDIT-130` |
| Приоритет | P3 (non-blocking, deferred candidate — но малый scope) |
| Домены | RAG (09) |
| Finding IDs | `rag:DOMAIN-P3-001` + `cycle-2:T-W3-01 RESIDUAL` |
| Пути файлов | `src/backend/services/ai/rag_service/{ingest,search,augment,collection}_mixin.py` (4 файла) |
| Зависимости | T-W0-01 |
| Параллельность | serial (Wave 3 = 1 task) |
| LOC range | -30 source (delete manual retry) / +5 source (`@retry` decorator) / +10 test |
| Rollback risk | low (tenacity already in `uv.lock` per `agents_pydantic/base.py:226`) |

**Минимальный diff:**
```python
# До: manual while-loop + sleep + max_attempts counter
for attempt in range(3):
    try:
        return await self._call(...)
    except (ConnectionError, TimeoutError):
        await asyncio.sleep(2 ** attempt)
return None  # silent

# После (cycle-4/D-AUDIT-130):
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
async def _call_with_retry(self, ...):
    return await self._call(...)
```

**Критерий "готово":**
```bash
.venv/bin/python -m pytest \
  tests/unit/services/ai/rag_service/test_tenacity_retry.py \
  --tb=short -q
```

**Гарантии:**
- ✅ tenacity уже в `uv.lock` (не увеличивает allowlist / lockfile)
- ✅ Не затрагивает обоснованно-НЕ-заменяемые outbox/reconnection (`INFRA-P3-001/002` per Ponytail)

---

## 6. Wave 4 — P4 organic feature (1 задача)

### T-W4-01 — Langchain RecursiveCharacterTextSplitter для RAG ingest

| Поле | Значение |
|---|---|
| Global task ID | `T-W4-01` |
| Docstring marker | `cycle-4/D-AUDIT-140` |
| Приоритет | P4 (organic, non-blocking) |
| Домены | RAG (09) |
| Finding IDs | `rag:DOMAIN-P4-002` + `cycle-3:T-11 deferred` |
| Пути файлов | `src/backend/services/ai/rag_service/ingest_mixin.py:35-48` (naive chunker) + новый optional chunker helper |
| Зависимости | T-W0-01 |
| Параллельность | serial (Wave 4 = 1 task) |
| LOC range | -10 source (delete naive chunker) / +15 source (`RecursiveCharacterTextSplitter`) / +10 test |
| Rollback risk | low (already-installed dep) |

**Минимальный diff:**
```python
# До: naive sliding-window chunker (cycles 1+2+3)
# После (cycle-4/D-AUDIT-140):
from langchain.text_splitter import RecursiveCharacterTextSplitter

class IngestMixin:
    _splitter = RecursiveCharacterTextSplitter(chunk_size=512, chunk_overlap=64)

    async def _chunk(self, text: str) -> list[str]:
        return self._splitter.split_text(text)
```

**Критерий "готово":**
```bash
.venv/bin/python -m pytest \
  tests/unit/services/ai/rag_service/test_recursive_chunker.py \
  --tb=short -q
```

---

## 7. Wave N — Deferred cycle 5+

> Все P0/P1 не из Wave 1/2 + все 42 P2 + 32 P3 (кроме T-W3-01) + 22 P4 (кроме T-W4-001) + Temporal Worker lifecycle (HIGH RISK).

| Deferred ID | Задача | Приоритет | Домены | Cycle 5+ reason |
|---|---|---|---|---|
| **N-1** | Temporal Worker lifecycle (`TemporalWorkerPool` instantiate + Typer CLI + 4 `@processor` decorators + cancel_workflow fail-CLOSED) | P0 (cycle-1 RESIDUAL) | workflow | **HIGH RISK**, требует ADR + `uv sync --extra workflow` + реальный Temporal-кластер |
| **N-2** | Agent DSL registration (16/17 processors + BindSkill orphan + agent_dsl template) | P1 | agents | mass-rename, separate PR-серия |
| **N-3** | Agent PII/guards runtime DI (`_resolve_tokenizer`/`_resolve_runtime`) | P0 | agents | DI-pattern requires PluginLoader refactor |
| **N-4** | AgentMemoryService tenant_id | P0 | agents | multi-tenant data breach, требует Mongo schema migration |
| **N-5** | HITL endpoints cleanup (router-level guard уже в Wave 2) | P1 | API | sub-task, не блокер |
| **N-6** | orders_dsl `.then()` AttributeError (`BL-P1-001`) | P1 | business-logic | runtime crash, но extensions scope |
| **N-7** | validate_inn(None) TypeError (`BL-P1-003`) | P1 | business-logic | 1-строчный fix |
| **N-8** | credit_pipeline_v2 default inconsistency (`BL-P2-003`) | P2 | business-logic | test-fixture + config fix |
| **N-9** | All 42 P2 cleanup (cross-domain) | P2 | cross | bulk cleanup, после Wave 1-4 |
| **N-10** | All 30 P3 library replacements (кроме T-W3-01) | P3 | cross | library migration |
| **N-11** | All 21 P4 organic features (кроме T-W4-01) | P4 | cross | organic additions |
| **N-12** | Test cleanup (INFRA-P0-001/002/003 + ENTRY-P1-002) | P1 | infrastructure | test-only, post-cycle 4 batch |
| **N-13** | Settings + dependencies cleanup (ENV-P1-001..005 + DOMAIN-P1-001..004 + DOMAIN-P2-001/002) | P1/P2 | settings + dependencies | cross-cutting refactor |
| **N-14** | Information disclosure на 6 endpoints (`DOMAIN-P1-006`) | P1 | API | role-guard sweep |
| **N-15** | Embedding cache test naming drift + 9 outbox arity failures + CDC doc-test sync | P0 | infrastructure | test fixes |
| **N-16** | AuthRequiredMiddleware + APIKeyMiddleware consolidation (`DOMAIN-P3-002`) | P3 | API | library replacement |
| **N-17** | OIDC support (`SECURITY-P4-001`) + SAML SLO | P4 | security | organic |
| **N-18** | AgentSecurityFramework wire-up (`AGENTS-P4-001`) | P4 | agents | extension integration |

**Отложено осознанно** для минимизации cycle-4 scope. Каждое N-item имеет docstring marker `cycle-4/D-AUDIT-NNN` reserved для cycle 5+.

---

## 8. Параллельные группы и dependency graph

### 8.1 Master parallel groups

```
Group 0 (serial, 1 коммит):
  └─ T-W0-01 (preflight)

Group 1 (serial, 1 коммит — critical path):
  └─ T-W1-01 (T-08 kwargs re-fix)

Group 2 (parallel, до 8 коммитов — RCE-tier + SAML):
  ├─ T-W1-02 (SAML impersonation)
  ├─ T-W1-03 (SQL policy context)
  ├─ T-W1-04 (defusedxml drop-in)
  ├─ T-W1-05a (admin_cron whitelist)
  ├─ T-W1-05b (ScriptRunner RCE)
  ├─ T-W1-05c (PickleDataFormat RCE)
  ├─ T-W1-06 (OSINT fail-OPEN)
  └─ T-W1-07 (AdminService fail-CLOSED)

Group 3 (parallel, 2 коммита — после T-W1-01):
  ├─ T-W1-08 (MQ consumer DLQ)
  └─ T-W1-09 (PII fail-CLOSED contract)

Group 4 (parallel, 3 коммита — после Group 2/3):
  ├─ T-W2-01 (HITL + SSE principal)
  ├─ T-W2-02 (Layer violations)
  └─ T-W2-03 (Webhook + admin_actions)

Group 5 (serial, 1 коммит):
  └─ T-W3-01 (tenacity for RAG)

Group 6 (serial, 1 коммит):
  └─ T-W4-01 (RecursiveCharacterTextSplitter)

Group 7 (deferred — cycle 5+):
  └─ N-1..N-18 (18 отложенных items)
```

### 8.2 Top dependencies

1. **T-W0-01** → блокирует все Wave 1/2/3/4
2. **T-W1-01** → блокирует T-W1-08 (tenant_id для DLQ payload) + T-W1-09 (tenant_id для PII AuditEvent) + T-W2-01 (tenant_id для HITL filter)
3. **T-W1-04** → независим (defusedxml hard-import) но используется T-W1-02 (SAML path)
4. **T-W2-02** → блокирует N-9 (P2 cleanup batch)
5. **T-W3-01** → независим, может идти параллельно с Wave 4

---

## 9. Rollback strategy

### 9.1 Per-task rollback

| Task | Rollback strategy | Risk level |
|---|---|---|
| T-W1-01 | `git revert <commit>` (1 строка source + test) | **low** |
| T-W1-02 | `git revert` (security guard; reverting восстанавливает bypass, но не ломает runtime) | low |
| T-W1-03 | `git revert` (signature extension; reverting = silent drop снова) | low |
| T-W1-04 | `git revert` (defusedxml hard-import; reverting восстанавливает XXE) | low |
| T-W1-05a/b/c | `git revert` per sub-task (RCE guard; reverting = RCE возвращается) | low |
| T-W1-06 | `git revert` (raises domain exception; reverting = silent echo) | low |
| T-W1-07 | `git revert` (admin guard; reverting = admin bypass) | low |
| T-W1-08 | `git revert` (DLQ-write; reverting = data-loss; интеграционный test required) | **medium** |
| T-W1-09 | `git revert` (PII fail-CLOSED; reverting = PII leak; audit event required) | **medium** |
| T-W2-01 | `git revert` (HITL guard; reverting = cross-tenant bypass) | medium |
| T-W2-02 | `git revert` (move CDCProcessor; reverting = layer violation) | low |
| T-W2-03 | `git revert` (HMAC + admin mock-fallback) | medium |
| T-W3-01 | `git revert` (tenacity decorator) | low |
| T-W4-01 | `git revert` (chunker swap) | low |

### 9.2 Cross-task rollback (cycle-level)

```bash
# Перед стартом Wave 1:
git tag cycle-4/phase-3-preflight <commit-after-T-W0-01>

# Аварийный full rollback (если Wave 1 сломал что-то):
git revert --no-commit cycle-4/phase-3..HEAD
git tag cycle-4/phase-3-rollback
git checkout cycle-4/phase-3-preflight
```

---

## 10. Verification gates (end-of-cycle)

### 10.1 После Wave 0

- `tools/check_layers.py --root src` → exit 0, 175/0 ✅
- `make check-docstrings MAX_ALLOWED=0` → exit 0 ✅
- `grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt` → 27 ✅
- `git diff --stat HEAD -- uv.lock` → 0 lines ✅
- 8 smoke-тестов → 8/8 PASS ✅

### 10.2 После Wave 1 (P0)

- 32 P0 findings → 9 RESOLVED + 23 RESIDUAL → **23 residual = N-1..N-5**
- 5 contradictions C-1..C-5 → все RESOLVED ✅
- `make lint && make type-check` → exit 0
- `.venv/bin/python -m pytest tests/ --tb=short -q` → green (или ≤3 pre-existing residuals per BASELINE.md)

### 10.3 После Wave 2 (P1 layer)

- 44 P1 findings → 7 RESOLVED + 37 RESIDUAL
- `tools/check_layers.py --root src` → 175/0 ✅ (НЕ 176/0)
- C-6 convergence RESOLVED ✅

### 10.4 После Wave 3+4

- 32 P3 findings → 1 RESOLVED + 31 RESIDUAL (cycle 5+ batch)
- 22 P4 findings → 1 RESOLVED + 21 RESIDUAL

### 10.5 End-of-cycle summary

```bash
# Verification block — выполнить перед merge cycle-4 branch:
.venv/bin/python tools/check_layers.py --root src
.venv/bin/python tools/check_docstrings.py
.venv/bin/python -m pytest tests/ --tb=short -q --ignore=tests/e2e
.venv/bin/python -c "import json; assert len(json.load(open('.security/pip-audit-allowlist.json'))['active']) == 27"
git diff --stat HEAD~11..HEAD -- uv.lock | wc -l    # → 0
grep -rn "cycle-4/D-AUDIT" src/backend | wc -l       # → N (commit count)
```

---

## 11. Out-of-scope (явно НЕ делается в cycle 4 Phase 3)

1. **8 правок cycle 1+2+3** (уже в HEAD 22e08a0d) — не переписывать.
2. **Pre-existing residual** `services/ai/gateway_adapter.py:128-129` (`except Exception: pass`) — не этому swarm.
3. **`uv.lock`** любые изменения — pre-existing drift вне scope.
4. **`pyproject.toml` cross-pin duplicates** (D-AUDIT-03 streamlit/lxml/pillow) — P3-001 deferred.
5. **Allowlist 27→N** — не растить.
6. **`.env`/`.env.*`/`secrets/**`** — запрещено per AGENTS.md.
7. **All 18 N-items** (cycle 5+) — отдельный план.
8. **Mobile BFF dead code** (`DOMAIN-P1-005`) — 438 LOC, `git rm` отдельным PR вне cycle-4 (touching entrypoints/api/mobile/* вне scope этого audit).

---

## 12. Резюме

| Метрика | Значение |
|---|---|
| **Wave 0 tasks** | 1 (T-W0-01) |
| **Wave 1 tasks** | 9 atomic (T-W1-01..09; T-W1-05 = 3 sub-commits) = **11 коммитов** |
| **Wave 2 tasks** | 3 (T-W2-01..03) |
| **Wave 3 tasks** | 1 (T-W3-01) |
| **Wave 4 tasks** | 1 (T-W4-01) |
| **Total Phase 3 tasks** | **15 (17 коммитов с под-задачами)** |
| **Wave N deferred** | 18 items (cycle 5+) |
| **Docstring markers** | `cycle-4/D-AUDIT-100`..`140` (allocated 41 номеров) |
| **Critical path** | T-W0-01 → T-W1-01 (1 source LOC) |
| **Parallel groups** | 7 групп; макс. 8 параллельных (Group 2) |
| **Resolved contradictions** | 5/5 (C-1..C-5) + 2 convergence (C-6, C-9) |
| **Baseline invariants preserved** | layer 175/0, allowlist 27, docstring 0, uv.lock 0 churn |
| **Pre-existing residuals not touched** | gateway_adapter.py:128-129, test_gateway_pipeline_mixin.py:54 |
| **Total estimated LOC delta** | +250 source / +250 test (net: ~+500 LOC) |

**Phase 3 contract:**
- T-08 TenantFacade kwargs re-fix = critical path (1 строка + regression test)
- 9 P0 + 3 P1 + 1 P3 + 1 P4 = **14 активных tasks**, остальное deferred
- Все runtime-тесты через `.venv/bin/python -m pytest`
- Запрет удалять `except Exception` без concrete handling (PII contract + DLQ-write добавляют handling)
- Русские docstrings не переводить (только marker `cycle-4/D-AUDIT-NNN`)