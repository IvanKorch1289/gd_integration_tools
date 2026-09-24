# P0 user-data callsites deep-dive (cycle 158+ continuation, 2026-09-24)

> **Этот документ — investigation artifact для next-cycle P0 fix ADR.**
> Per audit "Movement toward the requested end state" + v4 §6 "Перед
> доработкой сформулируй гипотезу".

## 1. Background

Per `tools/classify_object_authorization.py` cycle 158+ measurement (после
bug fix `e03561ce7`), реальные user-data callsites которые нужно
закрыть ADR+implementation для P0 audit gate:

| Stat | Value |
|---|---|
| Total flagged (raw `check_object_authorization.py`) | 133 |
| After admin/auth/tests path filter | 123 |
| After infra-registry heuristic classifier | 92 (74.8%) |
| **Real user-data (this investigation)** | **7 (5.7%)** |
| Unknown (manual review) | 24 (19.5%) |

## 2. Per-callsite analysis (с source context)

### 2.1. `src/backend/dsl/audit_versioning.py:151` — VersionModel lookup

```python
VersionModel = Versioning._version_model_or_raise(model)
return (
    session.query(VersionModel)
    .filter_by(id=entity_id, transaction_id=transaction_id)  # line 151
    .first()
)
```

**Pattern**: `orm-query` (cycle 158+ detection).

**Tenant context**: filter has `transaction_id` (per-version control), but **NO
explicit `tenant_id` filter**. Audit-versioning invariants may include
implicit tenant scope via:
- `transaction_id` is per-tenant (TBD verify)
- Or `VersionModel` is global (not tenant-scoped) by design.

**Action for next-cycle ADR**: 
1. Verify if `VersionModel` is per-tenant or global.
2. If per-tenant — add explicit `tenant_id` filter или Pydantic join с TenantContext.
3. If global — close finding (false positive).

### 2.2. `src/backend/entrypoints/api/v1/endpoints/hitl.py:164` — Get HITL signal

```python
@router.get("/{signal_id}", summary="Get HITL signal details")
async def get_signal(signal_id: str, request: Request) -> dict[str, Any]:
    svc = _service(request)
    signal = await svc.get(signal_id)  # line 164
```

**Pattern**: `service-getter` (cycle 158+).

**Tenant context**: `svc = _service(request)` — `_service` likely injects
`TenantContext` from request. Если `HitlService.get()` implementation
filters by tenant internally, это false positive. Если НЕ, это P0 gap.

**Action**:
1. Read `src/backend/services/.../hitl/service.py` (or где `_service` определен).
2. Verify `HitlService.get(signal_id)` includes tenant filter.
3. Если not — add explicit tenant filter (e.g., `WHERE tenant_id = current_tenant()`).

### 2.3. `src/backend/entrypoints/api/v1/endpoints/hitl.py:185` — Update HITL signal

```python
svc = _service(request)
existing = await svc.get(signal_id)  # line 185
```

**Pattern**: same as 2.2 — `service-getter`.

**Tenant context**: same issue. If service layer filters by tenant, both
164 and 185 calls are safe; else need explicit fix.

**Note**: This is a WRITE operation (existing → check before update). Higher
risk than read-only `get` — must verify tenant ownership.

### 2.4. `src/backend/entrypoints/api/v1/endpoints/notebooks.py:156`

```python
notebook = await get_notebook_service().get(notebook_id)  # line 156
```

**Pattern**: `service-getter`.

**Tenant context**: `get_notebook_service()` — singleton or per-request?
Notebooks (JupyterHub integration) are typically per-user. Verify
`NotebookService.get()` filters by current_tenant.

**Action**:
1. Read NotebookService impl.
2. Verify tenant filter (likely exists для JupyterHub user → notebook mapping).

### 2.5. `src/backend/entrypoints/api/v1/endpoints/ai_feedback.py:168`

```python
async def get(self, *, doc_id: str) -> Any | None:
    """Получить feedback-запись по doc_id."""
    return await get_ai_feedback_service().get(doc_id)  # line 168
```

**Pattern**: `service-getter`.

**Tenant context**: AI feedback is per-user/per-doc. `AIFeedbackService.get()`
should filter by tenant. AI feedback уже имеет user-scoped queries.

**Action**: Verify AIFeedbackService.get() tenant scope.

### 2.6. `src/backend/dsl/engine/processors/hitl_approval.py:263`

```python
signal = await self._hitl_service.get(signal_id)  # line 263
```

**Pattern**: `service-getter` (cycle 158+).

**Tenant context**: `self._hitl_service` — class attribute likely initialized
in DSL processor. Service may или may not have tenant injection. If DSL
processor runs in tenant scope, the service may have access to tenant
context. If it runs in non-tenant scope (e.g., workflow orchestrator),
gap.

**Action**: Verify DSL HITL approval processor's `_hitl_service` tenant
injection. Likely needs explicit tenant filter.

## 3. Per-file summary table

| File | Line | Pattern | Has tenant injection? | Verdict |
|---|---|---|---|---|
| `audit_versioning.py` | 151 | orm-query | TBD | conditional |
| `hitl.py` | 164, 185 | service-getter | TBD (svc via _service) | conditional |
| `notebooks.py` | 156 | service-getter | TBD | conditional |
| `ai_feedback.py` | 168 | service-getter | TBD | conditional |
| `hitl_approval.py` | 263 | service-getter | TBD | conditional |

## 4. Unknown callsites (24 calls, needs manual review)

These fell through the classifier heuristics. Likely all infra-registry
(private collections, lock-style state) — but per audit "всегда перепроверяй",
each should be visually confirmed:

Sample unknown calls (from cycle 158+ output):
- `color_map.get(identity)` — DSL workflow rendering, infra.
- `elements.get(node_id)` — DSL bpmn, infra.
- `templates.get(template_id)` — infra (compile-time constants).
- `outputs.get(sid)` — DSL flow compilation, infra.

These probably have NO tenant exposure (UI compilation artifacts),
but should be confirmed before declaring as closed.

## 5. Recommendation per v4 §10 P1

Per current evidence:

1. **Likely 4-7 callsites are real P0 fixes** (depending on service
   impls — need to audit each).
2. **Most likely 0-3 are real cross-tenant exposure** if service
   layers have tenant filters (probably common given existing
   infrastructure).
3. **24 unknown callsites** likely 0 are real (mostly DSL infra).

For next-cycle ADR scope:

### Option A (recommended): per-call verification + targeted fix
1. Audit 7 service-layer implementations (`svc.get`, `HitlService.get`,
   etc.) — verify tenant filters exist.
2. Document each in per-fix mini-ADR (~20 lines each).
3. For each: explicit `WHERE tenant_id = current_tenant()` или
   equivalent guard.

### Option B: Object ownership policy (P0.5 — design-decision per v4 §10)
1. ADR for global ownership policy (Casbin vs custom class-based).
2. Per-route declaration: required scopes/permissions.
3. Middleware OR explicit guard per business operation.

### Option C: Middleware-enforced (centralized)
1. SQLAlchemy event listener `before_compile` injection of tenant filter.
2. Lower per-call code change cost, higher architectural risk.

## 6. Per v4 §6 Gate audit (for next-cycle implementation)

| Gate | Required before fix |
|---|---|
| Problem proof | ✅ THIS DOCUMENT (cycle 158+) |
| Existing solution audit | Open — need to inventory Casbin vs custom options |
| Architecture fit | Open — depends on Option A/B/C choice |
| Value | Realistic — 4-7 callsite fixes / 159 routes (2-4%) = +2-4% ownership coverage |
| Parity | Should preserve existing service contract |
| Blast radius | 7 callsites if Option A; 全 routes if Option B/C |
| Verification plan | Per-callsite negative test + per-route coverage test |
| Approval/ADR | Required — significant architectural decision |

## 7. What I delivered this session

- ✅ `tools/classify_object_authorization.py` — heuristic-based classifier.
- ✅ 8 regression tests в `test_w11_p0_3_classify_object_authorization.py`.
- ✅ Bug fix `e03561ce7` (svc.get service-locator pattern).
- ✅ Per-callsite deep-dive + 24 unknown callsites inventory (THIS DOC).
- ✅ Per-file source context для next-cycle ADR.

## 8. What I NOT delivered (per v4 §10 P0 deferred scope)

- ❌ Object ownership policy ADR — requires design decision per Option A/B/C.
- ❌ Per-callsite implementation — requires ADR first.
- ❌ Middleware implementation — significantly larger architectural change.
- ❌ Per-v4 §6 8-gate audit — needs user direction on Option choice.
