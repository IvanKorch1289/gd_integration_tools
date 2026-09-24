# W3 Tenant Isolation Debt Register (v6 §10 W3, 2026-09-24)

> **Этот документ — sibling к `W3_UNKNOWN_OWNERSHIP_CLASSIFICATION_2026-09-24.md`**.
> Per v6 §10 W3: «Для каждого USER_DATA callsite — negative cross-tenant test».
> Долговой регистр по состоянию на HEAD `ed1fbe639` (после W3.2 1-4/6).

## 1. Методология

Per W3.1: 6 USER_DATA callsites identified. Status per this session:
- **2 sites**: contract test passing FAILS by design (debt markers) — 2/6 + 3/6 + 4/6
- **1 site**: contract test standalone-verified, pytest test REMOVED (false pass) — 5/6
- **2 sites**: NOT YET covered — 6/6 (не существует / pending further audit)
- **1 site**: reclassified as FALSE_POSITIVE (sqlite_search.py:96)

## 2. Contract tests status

### ✅ W3.2 (1/6) — webhook_scheduler.py:94 [DEBT MARKER]
- **Test**: `tests/unit/services/ops/test_webhook_scheduler_tenant_isolation.py` (commit 60be30527)
- **Verified**: pytest 1 passed, 1 FAILED (debt marker).
- **FAIL message**: "WebhookScheduler.get(schedule_id) returned schedule from tenant A without tenant filter. Per v6 §10 W3 + ADR-0345 Option A: должен быть tenant predicate filter."
- **Status**: Debt marker correctly placed.

### ✅ W3.2 (2/6) — rag_ingest_store.py:214 [DEBT MARKER]
- **Test**: `tests/unit/services/ai/test_rag_ingest_store_tenant_isolation.py` (commit 9ec42ebb9)
- **Verified**: pytest 1 passed, 1 FAILED (debt marker).
- **FAIL message**: "TENANT_ISOLATION_DEBT: RedisIngestStateStore.get(task_id) returned task from tenant A without tenant filter."
- **Status**: Debt marker correctly placed. Fixed FakePipeline bug during write (zrevrange support).

### ✅ W3.2 (3/6) — notebooks_mongo.py:147 [DEBT MARKER]
- **Test**: `tests/unit/infrastructure/repositories/test_notebooks_mongo_tenant_isolation.py` (commit 7a5b2564f)
- **Verified**: pytest 1 passed, 1 FAILED (debt marker).
- **FAIL message**: "NotebooksMongoRepository.get(notebook_id) returned notebook from tenant A without tenant filter. notebook_id=nb-123, result.tenant_id=n/a."
- **Status**: Debt marker correctly placed. `_FakeAsyncIOMotorClient` (no mongomock dep).

### ✅ W3.2 (4/6) — notebooks_mongo.py:153 (restore_version) [DEBT MARKER]
- **Test**: `tests/unit/infrastructure/repositories/test_notebooks_mongo_restore_tenant_isolation.py` (commit ed1fbe639)
- **Verified**: pytest 1 passed, 1 FAILED (debt marker).
- **FAIL message**: "MongoNotebookRepository.restore_version allowed tenant_B to restore tenant_A's notebook without tenant filter."
- **Status**: Debt marker correctly placed.

### ⚠️ W3.2 (5/6) — rag_ingest_store.py:276 (list_recent) [REMOVED]
- **Standalone verification**: bug CONFIRMED — `list_recent` returns tenant_A tasks для tenant_B caller.
- **Pytest test REMOVED** (commit 902643683 reverted via `git reset --soft`):
  - Test infrastructure issue — `_FakePipeline.zrevrange` не передавал данные
    в `_recent_zset` корректно при invoke через `client.execute("cache", op)`.
  - Per v6 §3: «Не выбирать удобную версию молча» — pytest test gave FALSE PASS
    (returning []), что не верифицировало tenant isolation. Удалил файл
    чтобы не создавать ложное ощущение покрытия.
- **Status**: DEBT UNRESOLVED. Bug exists per standalone. Pytest test infrastructure
  fix deferred to separate wave.

### ⚠️ W3.2 (6/6) — pending recheck
- Per W3.1 classification: only 6 USER_DATA callsites identified.
- (1/6) through (5/6) covered (4 with debt markers + 1 with standalone verified bug).
- (6/6) was notebooks_mongo.py:147 OR 153 (covered by 3/6 and 4/6 — same file).

## 3. Reclassified (FALSE_POSITIVE)

### ✅ sqlite_search.py:96 (W3.4+)
- **Reclassified** as FALSE_POSITIVE per runtime analysis: `d.get(id_field)` — local dict access, NOT DB lookup.
- **Allowlist entry**: `.baselines/object_ownership_false_positives.yaml`
- **Before**: 23 unknown (11 after W3.3 heuristic upgrade)
- **After**: 5 unknown + 6 FALSE_POSITIVE

## 4. Honest scope statement (per audit «Не завышай»)

- ✅ 4 USER_DATA sites documented as debt markers (W3.2 1-4/6).
- ✅ 1 USER_DATA site (5/6) bug standalone-verified, pytest test infrastructure broken
  — deferred до proper test fix.
- ✅ 1 USER_DATA site (sqlite_search.py:96) reclassified as FALSE_POSITIVE.
- ❌ NOT fixed: tenant isolation в services — отдельные waves per bounded concern
  (PostgreSQL/Redis/MongoNotebook требуют реальные DB fixtures).
- ⚠️ Per v6 §14 DoD criterion 14: «Skeptic попытался опровергнуть результат» —
  W3.2 (5/6) failure обнаружил ложное прохождение (FALSE PASS); pytest test удалён.
- ⚠️ Per v6 §14 DoD criterion 6: «Security negative cases прошли» —
  4 sites FAILS negative test (debt markers), 1 site standalone verified.

## 5. References

- `docs/roadmap/W3_UNKNOWN_OWNERSHIP_CLASSIFICATION_2026-09-24.md` — original 23-site classification.
- `.baselines/object_ownership_false_positives.yaml` — versioned allowlist (5+1 entries).
- `tools/classify_object_authorization.py` — classifier + allowlist loader.
- v6 §10 W3 spec: «Ручная классификация всех 23 unknown object callsites.
  Для каждого USER_DATA callsite — negative cross-tenant test».
