# Cycle 2 / T-W1-08 — D-AUDIT-10 (credit scoring fail-closed)

**Task ID:** T-W1-08 (cycle-2 Wave 1 / G1 — extensions)
**Finding:** 10-DOMAIN-P0-003 (PHASE-2-SUMMARY §5.4 cycle-1 RESIDUAL)
**Priority:** P0 (banking-critical)
**Docstring marker:** `D-AUDIT-10`
**Plan ref:** `docs/audit/swarm-2026-08-06/cycle-2/PHASE-3-PLAN.md` §3.8
**Date:** 2026-08-06
**Status:** ✅ DONE

---

## 1. Что было сломано

`extensions/credit_pipeline/agents/__init__.py:84` (pre-fix):

```python
base_score = 750  # Default for unknown
```

Inline-прогон подтвердил fail-OPEN: `scoring_agent({})` →

```python
{'agent': 'scoring_agent', 'client_id': 0, 'credit_score': 750,
 'risk_class': 'LOW', 'model_version': 's76-w1-rule-based-v1', 'stub': False}
```

`credit_score=750` → `decision_agent` threshold `_SCORE_APPROVAL_THRESHOLD=600` →
`approved=True`, `decision_label="APPROVE"`. **Любой пустой / неполный payload
(нет income, нет amount) → кредит APPROVE.** Banking-critical fail-OPEN.

PHASE-2-SUMMARY классифицирует как 10-P0-003 / D-AUDIT-10 (banking-critical).

---

## 2. Что починено

### 2.1 Реализация (`extensions/credit_pipeline/agents/__init__.py`)

Перед вычислением `base_score` добавлена явная проверка на empty/incomplete
payload (`income <= 0 or amount <= 0`). В этом случае:

1. Emit audit-event `credit_rejected` через canonical
   `core.audit.facade.emit_audit_safe` (sync-safe variant, Path A pattern;
   не raise при failure — но logging pipeline сохранён).
2. Early-return с `credit_score=0`, `risk_class="HIGH"`, `reason="unknown_tenant"`.
3. Chained `decision_agent` → `credit_score=0 < 600` →
   `approved=False`, `decision_label="REJECT"`.

Docstring-комментарий в агенте ссылается на:

- `D-AUDIT-10` marker (banking-critical fix).
- Per-plugin lifecycle: scoring_agent работает только в контексте
  `CreditPipelinePlugin`, зарегистрированного через
  `extensions/credit_pipeline/plugin.toml` (capability
  `db.write credit_applications`). Без валидного payload tenant-контекст
  не может быть разрешён → REJECT (fail-closed).

### 2.2 Audit event

```python
await emit_audit_safe(
    event="credit_rejected",
    action="score",
    outcome="failure",
    severity="warning",
    details={
        "reason": "unknown_tenant",
        "client_id": int(client_id),
        "tenant_id": payload.get("tenant_id", ""),
    },
)
```

Используется canonical facade `core.audit.facade.emit_audit_safe` —
async-safe variant, never-raises (Path A pattern, S107 W3). Audit-failure
не ломает бизнес-логику (см. `_base.py` `_safe variant per design`).

### 2.3 Per-plugin lifecycle / plugin.toml capability

Не требуется runtime-check: `scoring_agent` работает только если
`CreditPipelinePlugin` зарегистрирован через `plugin.toml` lifecycle
(`on_load → on_register_actions`). Без этого `_make_handler` wrapper
в `plugin.py:44-58` не доступен. Capability `db.write credit_applications`
(manifest §db.write block) задекларирована — runtime gate через
`core.plugin_runtime.CapabilityGate` вне scope cycle 2.

---

## 3. Diff stat

```
 extensions/credit_pipeline/agents/__init__.py                       | +27 -2
 tests/unit/extensions/credit_pipeline/test_scoring_fail_closed.py   | +39 (new)
```

Scope строго ограничен T-W1-08: один production-модуль + один новый
тест-файл. Никаких изменений в `extensions/credit_pipeline/plugin.py`
(per-plugin lifecycle архитектурный invariant — не трогаем), `domain/`,
`functions/`, `workflows/`, `routes/`.

---

## 4. Tests

### 4.1 Новый файл: `tests/unit/extensions/credit_pipeline/test_scoring_fail_closed.py`

≤40 LOC (фактически 19 LOC без docstrings/imports), 3 test-функции:

1. `test_scoring_unknown_tenant_rejected` — `scoring_agent({})` →
   `credit_score=0`, `risk_class="HIGH"`, `reason="unknown_tenant"`.
2. `test_decision_chained_rejects_unknown_tenant` — pipeline
   `score → decision` → `approved=False`, `"REJECT"` в reason.
3. `test_scoring_incomplete_payload_rejected` — payload без
   `monthly_income` (но с amount) → REJECT.

### 4.2 Inline-прогон

```
$ python -c "from extensions.credit_pipeline.agents import scoring_agent; \
              import asyncio; \
              print(asyncio.run(scoring_agent({})))"

{'agent': 'scoring_agent', 'client_id': 0, 'credit_score': 0,
 'risk_class': 'HIGH', 'reason': 'unknown_tenant',
 'model_version': 's76-w1-rule-based-v1', 'stub': False}
```

`clickhouse_connect` недоступен в dev_light → `ClickHouseAuditService.emit`
log'ает warning, но не raise (safe variant contract). Бизнес-логика
не сломана.

### 4.3 Test results

```
$ pytest tests/unit/extensions/credit_pipeline/ -v

tests/unit/extensions/credit_pipeline/test_scoring_fail_closed.py::test_scoring_unknown_tenant_rejected PASSED
tests/unit/extensions/credit_pipeline/test_scoring_fail_closed.py::test_decision_chained_rejects_unknown_tenant PASSED
tests/unit/extensions/credit_pipeline/test_scoring_fail_closed.py::test_scoring_incomplete_payload_rejected PASSED
... 10 pre-existing test_real_agents.py PASSED ...
13 passed in 3.06s
```

```
$ pytest extensions/credit_pipeline/tests/ -v

33 passed, 1 failed (test_credit_pipeline_v2_flag_exists_and_default_off — pre-existing)

# Pre-existing verification:
$ git stash && pytest extensions/credit_pipeline/tests/test_credit_pipeline_v2_flag.py
1 failed in 4.91s  ← fail и до моего fix, это pre-existing feature-flag drift
$ git stash pop
```

`test_credit_pipeline_v2_flag_exists_and_default_off` — pre-existing failure
(feature flag `credit_pipeline_v2` returns True, expected False). Не связано
с T-W1-08. Зафиксировано в BASELINE.md / PHASE-2-SUMMARY как pre-existing
drift, вне scope cycle 2.

`test_actions_registration.py` (8 тестов): все PASSED (нет regression).

---

## 5. Verify gates

### 5.1 `tools/cycle-1-preflight.sh`

```
cycle-1 preflight (T-0.1 re-run):
  [OK]   layer checker — 0 new, 175 legacy
  [OK]   allowlist active IDs — 35
  [OK]   docstring gate — 0 missing
  [FAIL] working tree — 24 entries (разобраться)
  [FAIL] uv.lock churn — 40 lines (проверить не растёт ли)
  [OK]   s3.py untouched — не modified

Preflight failed — fix before running developer task.
```

**Разбор:**

- working tree 24 entries: 17 cycle-1 uncommitted (T-0.1 / T-1.4 / T-1.5 /
  T-3.1 / cycle-1 tests) + 2 моих файла (`agents/__init__.py` modified +
  `test_scoring_fail_closed.py` new) + 5 untracked pre-existing
  (`.blue_green.state`, `pip-audit.json`, `tests/unit/dsl/...` pre-existing
  тесты). Это **НЕ** pre-existing baseline drift увеличено — это
  structural reality cycle-1 + cycle-2 work-in-progress.
- uv.lock churn 40 lines: git diff показал **ровно 15 deletions** (pre-existing
  `-15 svcs` из BASELINE.md). 40 = `wc -l` от unified diff format
  (15 deletions × ~2.7 lines каждое). Pre-existing drift, не моё изменение.

Preflight exits 1 из-за **pre-existing issues** (cycle-1 uncommitted + uv.lock
drift). Это в соответствии с BASELINE.md / PHASE-3-PLAN.md §9.1 — НЕ моя
ответственность, ответственность developer commit step.

### 5.2 `make check-docstrings MAX_ALLOWED=0`

```
Files scanned: 838
[32mdocstring policy OK[0m
```

0 missing docstrings.

### 5.3 `python tools/check_layers.py --root src`

```
Нарушений: 0 новых  (файлов: 2274; baseline: 175 legacy)
```

0 new layer violations; baseline 175 legacy сохранён.

### 5.4 Security allowlist

```
$ grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt
35
```

35 active IDs (no-growth gate).

---

## 6. Compliance with constraints

| Ограничение | Compliance |
|---|---|
| Не трогать `uv.lock` | ✅ не модифицирован (`git diff uv.lock` показывает только pre-existing -15 svcs) |
| Не трогать `.security/pip-audit-allowlist.txt` | ✅ не модифицирован (35 active) |
| Не трогать `src/backend/infrastructure/storage/s3.py` | ✅ не модифицирован |
| Не трогать `tools/blue_green.sh` | ✅ не модифицирован |
| Не трогать `tests/unit/tools/test_blue_green_switch.py` | ✅ не модифицирован |
| Не переписывать 5 uncommitted cycle-1 правок (T-0.1, T-1.4, T-1.5, T-3.1) | ✅ не трогал |
| Не удалять `except Exception` без concrete handling | ✅ нетронуто |
| Docstring marker `D-AUDIT-10` (banking-critical) | ✅ в `agents/__init__.py:85` |
| Русские docstrings не переводить | ✅ оригинальный русский сохранён |
| Test ≤40 LOC | ✅ 19 LOC без docstrings/imports |
| Per-plugin lifecycle / plugin.toml capability | ✅ docstring + manifest ref |
| Audit event `credit_rejected` + reason `unknown_tenant` | ✅ `emit_audit_safe(event="credit_rejected", details={"reason": "unknown_tenant"})` |
| `make format`/lint/type-check | ✅ ruff, type hints |
| Python 3.14+ async-first | ✅ `await emit_audit_safe(...)` |
| Capability-checked фасады | ✅ `core.audit.facade.emit_audit_safe` (canonical) |

---

## 7. Rollback risk

Низкий. Изменения в одном production-файле (`agents/__init__.py`) +
новый тест. Behavior change только для edge case (empty/incomplete
payload), который ранее давал banking-critical fail-OPEN. Все 10
pre-existing credit_pipeline тестов проходят без модификации. Все 8
`test_actions_registration.py` тестов проходят (включая
`test_action_handles_missing_payload` / `test_action_handles_explicit_none_payload`
— они проверяют только `agent` + `stub=False`, не score).

При необходимости rollback: revert commit, изменения изолированы в
`scoring_agent` (одна функция, ~25 LOC). `audit.emit` call
идемпотентен (event-sourcing).

---

## 8. References

- `docs/audit/swarm-2026-08-06/cycle-2/PHASE-3-PLAN.md` §3.8 (T-W1-08 spec)
- `docs/audit/swarm-2026-08-06/cycle-2/BASELINE.md` (pre-existing drift)
- `docs/audit/swarm-2026-08-06/cycle-2/PHASE-2-SUMMARY.md` §5.4 (10-P0-003)
- `extensions/credit_pipeline/agents/__init__.py:85-114` (fix)
- `tests/unit/extensions/credit_pipeline/test_scoring_fail_closed.py` (new)
- `src/backend/core/audit/facade/_base.py` (emit_audit_safe contract)
- `extensions/credit_pipeline/plugin.toml` (capabilities: db.write)
- `extensions/credit_pipeline/plugin.py` (per-plugin lifecycle)
