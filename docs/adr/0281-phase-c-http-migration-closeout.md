# ADR-0281: HTTP-migration Phase C close-out (S34 W1)

> **Status**: ACCEPTED (2026-08-27).
> **Method**: minimal backend endpoint + client + facade deletion + frontend migration.
> **Scope**: Phase C close-out from SPRINT_33_RETRO §5.1 (2 facade symbols deferred).
> **Date**: 2026-08-27.
> **Commits**: `b348392b` (dead code) + `34007455` (audit endpoint).

## 0. Контекст

Sprint 32 NS-3 начал миграцию frontend → HTTP clients. Sprint 33 W1 закрыл 5/7
HTTP-equivalent facade violations через `/admin/workflow-versioning` endpoint.

Sprint 33 retro §5.1 отметил 2 symbols без HTTP endpoints → Phase C deferred:
1. `list_recent_trace_events` — DEAD CODE (после S44 W1 + S47 W1 рефакторинга,
   `ExecutionTracer._recent_events` атрибут удалён; `getattr` fallback всегда
   возвращал `[]`).
2. `list_audit_records` — queries **Redis stream** `audit:events` (НЕ ClickHouse
   `workflow_audit` table, к которому `/admin/workflow-audit/events` уже
   подключён). Требует **нового endpoint**.

Sprint 34 gap-agent (см. `SPRINT_34_GAP_ANALYSIS_2026-08-27.md` §1) обнаружил
оба bugs **independently** и предложил unified Phase C close-out.

## 1. Рассмотренные варианты

### Вариант A: Оставить facade (статус-кво Sprint 33)

**Pros**: zero work, no risk.
**Cons**: 2 dead-code-like symbols (один реально dead); `34_DSL_Отладчик.py`
silently empty Route Trace; audit replay UI требует curl.

**VERDICT**: ❌ Отклонён. Real bugs не fix.

### Вариант B: DELETE только `list_recent_trace_events`, оставить `list_audit_records`

**Pros**: только easy half.
**Cons**: оставляет facade API inconsistent (1 symbol imported, 1 deleted);
audit replay UI не работает.

**VERDICT**: ❌ Отклонён. Partial fix.

### Вариант C: Unified Phase C close-out (current ADR)

**Pros**: closes 2 symbols в 2 commits, real bug fixes оба.
**Cons**: 1 new endpoint (~75 LOC + tests) требует admin auth scope + Pydantic schema.

**VERDICT**: ✅ ADOPT.

## 2. Решение

**2 atomic commits**:

### Commit A: DELETE dead code + public history client (`b348392b`)

- DELETE `list_recent_trace_events` из:
  - `src/backend/services/dsl_portal/builder_facade.py:279-283` (impl)
  - `src/backend/core/frontend_facade.py:39, 76` (re-exports)
  - `src/backend/services/dsl_portal/__init__.py:45, 74` (exports)
- `34_DSL_Отладчик.py` → `DSLRoutesClient().get_dsl_route_traces(route_id, ...)`
  (real HTTP endpoint, persistent storage per TD-026).
- `WorkflowsClient.get_workflow_versioning_history()` — public method
  (S-34.1 review fix).

### Commit B: NEW audit endpoint + client (`34007455`)

- `src/backend/entrypoints/api/v1/endpoints/admin_audit_replay.py` —
  `GET /api/v1/admin/audit/capability` (admin role, 1..1000 count).
- `src/frontend/streamlit_app/api_clients/audit.py` — `AuditClient().list_records()`.
- `routers.py:73-75, 218-220` — registration с tag `"Admin · Audit Replay"`.
- `34_DSL_Отладчик.py:97-101` → `AuditClient().list_records(count=limit)`.
- `tests/unit/entrypoints/api/v1/endpoints/test_admin_audit_replay.py` — 5 tests.

## 3. Consequences

### Positive
- ✅ **HTTP-migration Phase C fully complete** (2 facade symbols → 0).
- ✅ **Real bug fixes** (silent empty UI → working trace/audit replay).
- ✅ **Defense-in-depth** (HTTP scope = backend capability check).
- ✅ **Single mock target** в тестах (HTTP → no need to mock Python facade).
- ✅ **+1 new endpoint** для HTTP-replay UI (debug tooling).

### Negative
- (−) 59 routes (was 58). Минимальное увеличение OpenAPI surface.
- (−) Defensive mapper overhead (~30 LOC) — acceptable для safety.

### Neutral
- Pre-existing `frontend_facade.py` entry #40 (→ `services.dsl_portal`)
  остаётся — out of scope (multi-sprint, ADR-0282).

## 4. Verification (machine-check)

```bash
# 1. Dead code + facade imports fully deleted
$ grep -rn "list_recent_trace_events" src/backend/ src/frontend/
# expected: 0

$ grep -rn "list_audit_records" src/backend/core/frontend_facade.py
# expected: 0

# 2. Frontend migrated to HTTP clients
$ grep -rn "from src.backend.core.frontend_facade import" \
    src/frontend/streamlit_app/pages/34_DSL_Отладчик.py
# expected: 0 (only comment about history)

# 3. Tests pass
$ pytest tests/unit/frontend/test_no_frontend_facade_regression.py -v
# expected: 3/3 PASS

$ pytest tests/unit/entrypoints/api/v1/endpoints/test_admin_audit_replay.py -v
# expected: 5/5 PASS

# 4. New endpoint registered
$ grep "audit/capability" src/backend/entrypoints/api/v1/routers.py
# expected: 1 (include_router)

# 5. Layer check
$ make layers
# expected: 0 NEW violations, 62 legacy (unchanged)
```

Все 5 условий выполнены.

## 5. Related

- `SPRINT_33_RETRO_2026-08-27.md` §5.1 — carry-over context
- `SPRINT_33_GAP_ANALYSIS_2026-08-27.md` §1, §4 — discovery rationale
- `SPRINT_34_GAP_ANALYSIS_2026-08-27.md` — Phase C inventory + verification
- ADR-0279 (circuit-breaker refactor) — pattern для cross-layer ADR
- ADR-0280 (LISTEN/NOTIFY defer) — pattern для ADR-only deferral
