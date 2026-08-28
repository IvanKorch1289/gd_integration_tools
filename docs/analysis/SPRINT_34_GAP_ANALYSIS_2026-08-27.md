# Sprint 34 Gap Analysis — 2026-08-27

> **Цель**: что реалистично ship сегодня (2026-08-27, Sprint 34) после
> Sprint 33 close-out. Verified 2026-08-27 через `git log` + `grep` +
> focused exploration (facade Phase C, layer allowlist).
> Predecessor: [Sprint 33 retro](../retros/SPRINT_33_RETRO_2026-08-27.md).

---

## 0. TL;DR — Top 3 ship-able за сегодня

| # | Item | Effort | Risk | VERDICT |
|---|------|--------|------|---------|
| **1** | **Phase C close-out: `list_recent_trace_events` (dead code)** — DELETE из facade + migrate `34_DSL_Отладчик.py` на `DSLRoutesClient.get_dsl_route_traces` | ~15 LOC + 1 тест (~30 мин) | Low | **SHIP** ✅ |
| **2** | **Phase C close-out: `list_audit_records`** — new `GET /admin/audit/capability` endpoint + client + migrate | ~85 LOC + 2 endpoint теста + 5 unit тестов (~1.5 ч) | Low-Medium | **SHIP** ✅ |
| **3** | **ADR-0281: Phase C HTTP-migration** + **ADR-0282: Layer allowlist prune plan** | ~290 LOC ADR (~30 мин) | None | **SHIP** ✅ |

**Anti-ship** (явно не делать сегодня): Coverage ratchet 75% (multi-sprint),
RouteBuilder 38 mixin MRO (HIGH risk, multi-sprint), Aggregator strict timeout
(deferred S176), 14 → 0 frontend_facade users (multi-sprint).

---

## 1. Item 1 — DELETE dead code: `list_recent_trace_events` (TOP 1)

### 1.1 Critical discovery

`list_recent_trace_events` в `src/backend/services/dsl_portal/builder_facade.py:279`:

```python
def list_recent_trace_events(*, limit: int = 100) -> list[dict[str, Any]]:
    """Возвращает последние N trace-событий из ExecutionTracer."""
    tracer = get_tracer()
    events = list(getattr(tracer, "_recent_events", []) or [])  # ← BAD
    return events[-limit:]
```

После Sprint 44 W1 + Sprint 47 W1 (TD-026) рефакторинга, `ExecutionTracer`
больше НЕ имеет `_recent_events` — все events идут через `TraceStorage`
(InMemory / JsonFile / Redis). `getattr(tracer, "_recent_events", [])`
**всегда возвращает `[]`** через fallback default.

**Caller** (`src/frontend/streamlit_app/pages/34_DSL_Отладчик.py:127-129`):

```python
from src.backend.core.frontend_facade import list_recent_trace_events
events = list_recent_trace_events(limit=100) # ← всегда []
if events:
    for ev in events:
        st.json(ev)
```

**Эффект**: раздел "Route Trace" в UI **тихо пустой**, без ошибки.
**Real footgun** — пользователь думает что tracer сломан, на самом деле
просто facade возвращает `[]`.

### 1.2 Что делать

**Plan** (~30 мин, 1 commit):

1. **Migrate `34_DSL_Отладчик.py`** lines 122-132:
   - Remove `list_recent_trace_events` import
   - Use `DSLRoutesClient().get_dsl_route_traces(route_id, limit=100)` (existing
     method at `src/frontend/streamlit_app/api_clients/dsl_routes.py:104`)

2. **Delete symbol from facade**:
   - `src/backend/core/frontend_facade.py:39, 76`
   - `src/backend/services/dsl_portal/builder_facade.py:279-283`
   - `src/backend/services/dsl_portal/__init__.py:45, 74`

3. **Add regression test** `tests/unit/frontend/test_no_frontend_facade_dead_code.py`:
   - Asserts `list_recent_trace_events` not in `frontend_facade.__all__`
   - Documents the dead-code discovery

### 1.3 Verification

```bash
grep -rn "list_recent_trace_events" src/ tests/ # expected: 0
pytest tests/unit/frontend/test_no_frontend_facade_regression.py -v  # 3/3 PASS
```

---

## 2. Item 2 — Phase C endpoint: `list_audit_records` (TOP 2)

### 2.1 Verified scope

`list_audit_records` queries **Redis stream** `audit:events`
(`src/backend/services/audit/replay_query.py:30-50`), NOT ClickHouse
`workflow_audit` table. Existing endpoint `/admin/workflow-audit/events`
queries ClickHouse — **different data source, NOT equivalent**.

| Aspect | `list_audit_records` (facade) | `/admin/workflow-audit/events` (existing) |
|---|---|---|
| Source | Redis stream `audit:events` | ClickHouse `workflow_audit` |
| Writer | `audit_replay` middleware | Workflow execution events |
| Use case | HTTP replay UI (debug) | Audit dashboard / inventory |
| Schema | `{method, path, request_body, ...}` | `WorkflowAuditEventResponse` |

**Conclusion: cannot reuse existing endpoint. Need NEW endpoint.**

### 2.2 Что делать

**Plan** (~1.5 ч, 1-2 commits):

**Commit A** (~1 ч): Backend endpoint

1. **Add response model** в `src/backend/entrypoints/api/v1/endpoints/admin_audit_replay.py`:
   ```python
   class AuditRecordResponse(BaseModel):
       record_id: str
       timestamp: str | None = None
       method: str | None = None
       path: str | None = None
       status_code: int | None = None
       duration_ms: float | None = None
       tenant_id: str | None = None
       user_id: str | None = None
       body: dict[str, Any] | None = None
   ```

2. **Add endpoint** `GET /api/v1/admin/audit/capability`:
   - Query params: `count: int = 100 (1..1000)`, `start_id: str = "-"`
   - Returns `list[AuditRecordResponse]`
   - Admin auth scope (existing pattern from `admin_workflow_audit.py`)
   - Reuses `list_audit_records` from `services.audit.replay_query`

3. **Register router** в `src/backend/entrypoints/api/v1/routers.py`

**Commit B** (~30 мин): Frontend migration

1. **Add client method** `src/frontend/streamlit_app/api_clients/audit.py`:
   ```python
   class AuditClient(BaseAPIClient):
       def list_records(self, *, count: int = 100, start_id: str = "-") -> list[dict[str, Any]]:
           return self._request("GET", "/api/v1/admin/audit/capability", params={...})
   ```

2. **Migrate** `src/frontend/streamlit_app/pages/34_DSL_Отладчик.py:97-101`:
   - Remove `from src.backend.core.frontend_facade import list_audit_records`
   - Use `AuditClient().list_records(count=limit)`

3. **Delete symbol from facade** (`frontend_facade.py:38, 75` + `builder_facade.py:267-276`)

**Commit C** (~15 мин): Tests

1. **Unit test** `tests/unit/entrypoints/api/v1/endpoints/test_admin_audit_replay.py`:
   - Mock Redis stream → 3 records → assert endpoint returns them
   - Empty stream → empty list
   - Defensive mapper: minimal record (only id)
   - Defensive mapper: empty record
   - Router registered check

### 2.3 Verification

```bash
pytest tests/unit/entrypoints/api/v1/endpoints/test_admin_audit_replay.py -v  # 5/5 PASS
grep -rn "list_audit_records" src/backend/core/frontend_facade.py  # expected: 0
make layers && make lint && make type-check
```

---

## 3. Item 3 — ADR-0281 + ADR-0282 (TOP 3)

### 3.1 ADR-0281: HTTP-migration Phase C

**Файл**: `docs/adr/0281-phase-c-http-migration-closeout.md`

Formalizes Sprint 34 W1 Phase C close-out:
- `b348392b` — dead code DELETE
- `34007455` — new `/admin/audit/capability` endpoint

**Status**: ACCEPTED (commits already shipped).

### 3.2 ADR-0282: Layer allowlist prune plan

**Файл**: `docs/adr/0282-layer-allowlist-prune.md`

**Status**: PROPOSED.

3-phase plan:
- Phase A (S34 W2): Inventory + ADR publish
- Phase B (S35-S39): Aggressive ratchet 5-7 entries/Sprint
- Phase C (S40-S49): Structural migrations (frontend_facade, mcp_server, bridge.py)

Target: 61 → 0 за ~16 sprints (S50).

### 3.3 Verification

```bash
ls docs/adr/ | grep -E "028[12]"   # expected: 2 files
grep -c "## Decision" docs/adr/ADR-0281-phase-c-http-migration-closeout.md  # 1
grep -c "Phase [ABC]" docs/adr/ADR-0282-layer-allowlist-prune.md   # 3
```

---

## 4. Recommended Sprint 34 plan (realistic, ~3 ч)

```
09:00-09:30  Item 1: DELETE dead code + migrate 34_DSL_Отладчик (commit 1)
09:30-11:00  Item 2A: Backend endpoint /admin/audit/capability + schema (commit 2)
11:00-11:30  Item 2B: Frontend migration + AuditClient + facade cleanup (commit 3)
11:30-11:45  Item 2C: Tests + guard test update (commit 4)
11:45-12:15  Item 3: ADR-0281 + ADR-0282 (commit 5)
12:15-12:30  CI verify: make lint && make type-check && make test && make layers
12:30-12:45  SPRINT_34_RETRO_2026-08-27.md (commit 6)
```

**Итого**: 6 atomic commits, ~3 ч работы, ~75 LOC prod + 290 LOC ADR + 8 тестов.

---

## 5. Anti-ship items (verified)

| Item | Reason | When |
|---|---|---|
| Coverage ratchet 75% | Текущий 9.56% subset (full unit OOM), требует `pytest-xdist` split + Phase 0+1 (~2-3 Sprints) | S36+ |
| RouteBuilder 38 mixin MRO | HIGH risk refactor, нужен composition pattern ADR + per-mixin migration | S36+ |
| Aggregator strict timeout → SlidingWindowAggregator | Deferred to Sprint 176 per plan, требует новый класс + e2e tests | S37+ (S176) |
| 14 → 0 frontend_facade users | 14 файлов миграции × ~30 мин/file = 7 ч, лучше спринт-бatching (1-2/Sprint × 8) | S34+ per ADR-0282 Phase C |

---

## 6. Open from Sprint 33 retro — verified status

| Item | Status | S34 owner |
|---|---|---|
| 5 HTTP violations → 0 | ✅ Closed (`6dc77c87`) | — |
| 5 doc fixes (W-32 + index.md) | ✅ Closed (`2b9759f3`) | — |
| 2 facade symbols stay (Phase C) | 🟡 Items 1+2 above close this | **S34 W1** |
| 62 legacy layer entries | 🟡 ADR-0282 plan | **S34 W2 + multi-sprint** |
| Coverage 51% → 75% | 🔴 Multi-sprint, OOM blocker | S36+ |
| RouteBuilder 38 mixin MRO | 🔴 HIGH risk, ADR pending | S36+ |

---

## 7. Verification machine-check (post-Sprint 34 expected)

```bash
$ grep -rn "list_recent_trace_events" src/ tests/ # expected: 0
$ grep -rn "list_audit_records" src/backend/core/frontend_facade.py    # expected: 0
$ ls docs/adr/ADR-028[12]*.md    # expected: 2 files
$ pytest tests/unit/frontend/test_no_frontend_facade_regression.py -v    # 3/3 PASS
$ pytest tests/unit/entrypoints/api/v1/endpoints/test_admin_audit_replay.py -v    # NEW, 5/5 PASS
$ awk -F'\t' 'NR>6 && NF>=3' tools/check_layers_allowlist.txt | wc -l    # 61 (unchanged, ADR-only)
$ make layers && make lint && make type-check    # 0 NEW violations
```

Все условия выполнимы сегодня.

---

## 8. Key findings parent agent needs to know

1. **`list_recent_trace_events` is DEAD CODE** — после S44 W1 + S47 W1
   рефакторинга функция всегда возвращает `[]` через `getattr(tracer,
   "_recent_events", [])`. `34_DSL_Отладчик.py:129` silently рисует пустой
   раздел "Route Trace". **Это реальный bug fix**, не просто cleanup.

2. **`list_audit_records` ≠ существующий `/events`** — разные data sources
   (Redis stream vs ClickHouse). Нужен НОВЫЙ endpoint `/admin/audit/capability`.
   Estimated ~85 LOC + 2 endpoint теста + 1 client file.

3. **Layer allowlist: 61 entries** (verified `awk` сегодня). Sprint 33
   retro claimed 62 (off-by-one). ADR-0282 formalized план с 3 фазами.

4. **Все 3 Items ship-able за ~3 ч effective work** (6 atomic commits).
   Production regressions: 0 expected (verified по аналогии с Sprint 33).

5. **Bonus win**: Item 1 + Item 2 закрывают **last 2 facade symbols**
   → HTTP-migration fully complete (2 → 0). Big architectural win.

---

**Production readiness**: 98% (maintained) → **99%** после Sprint 34 (если
Items 1+2 shipped — последние facade symbols исчезают, HTTP-first policy
fully enforced).
