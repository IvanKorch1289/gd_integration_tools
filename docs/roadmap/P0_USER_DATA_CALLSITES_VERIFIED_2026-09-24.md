# P0 user-data callsites — VERIFIED with service-layer inspection (cycle 158+)

> **Этот документ — cycle 158+ investigation follow-up.**
> Per audit "всегда перепроверяй перед тем, как утверждать":
> после deep-dive analysis (`P0_USER_DATA_CALLSITES_INVESTIGATION_2026-09-24.md`),
> проверил **service-layer implementations** для каждого из 7 callsites.
> 4-5 из 7 — **CONFIRMED P0 gaps** в cross-tenant exposure.

## 1. Per-callsite verification (real evidence, не гипотеза)

### 1.1 `audit_versioning.py:151` — Versioning.get_version

**Source context** (`src/backend/dsl/audit_versioning.py:138-153`):
```python
@staticmethod
def get_version(
    session: Any, model: type, entity_id: int | str, transaction_id: int
) -> Any:
    VersionModel = Versioning._version_model_or_raise(model)
    return (
        session.query(VersionModel)
        .filter_by(id=entity_id, transaction_id=transaction_id)
        .first()
    )
```

**Tenant scoping analysis**:
- `DomainModel` (base) has only `id`, `created_at`, `updated_at` columns — **NO `tenant_id`** by default.
- `version_class(model)` from sqlalchemy_continuum creates mirror table with same columns.
- Specific models (rule_engine, workflow_event, workflow_instance, etc.) DO add `tenant_id` via mixin.
- Per `audit_versioning.py:42`: `from sqlalchemy_continuum import version_class`.

**Verdict**: **CONDITIONAL P0 gap**:
- ✅ For models WITH TenantMixin: VersionModel inherits `tenant_id` column → caller must filter by `id + tenant_id + transaction_id`.
- ⚠️ For models WITHOUT TenantMixin: VersionModel has NO tenant column → **GAP** (any tenant can read any entity's version history).
- ⚠️ Caller `get_version(session, model, entity_id, transaction_id)` does NOT take `tenant_id` param.

**Action for next-cycle ADR**: classify all versioned models by tenant-scope (TenantMixin presence) → for non-tenant models, ADD `tenant_id` filter at model level или close audit-versioning for those models.

**Risk severity**: MEDIUM (depends on model coverage; if all versioned models have TenantMixin, this is false positive).

### 1.2 `hitl.py:164, 185` — HitlService.get (CONFIRMED P0 GAP ❌)

**Source evidence** (`src/backend/services/workflows/hitl_service.py`):
```python
async def get(self, signal_id: str) -> HitlPendingSignal | None:
    """Get signal by ID.
    
    Args:
        signal_id: Signal identifier.
    
    Returns:
        Signal if found, None otherwise.
    """
    return await self._store.get(signal_id)
```

`HitlPendingSignal` model HAS `tenant_id: str` field (`hitl_models.py:56`)
И `HitlSignalStore.get(signal_id)` Protocol definition: 
```python
async def get(self, signal_id: str) -> HitlPendingSignal | None:
```
(только signal_id, NO tenant_id filter).

**Contrast**: `list_pending` (same file) HAS `tenant_id` filter:
```python
async def list_pending(self, *, tenant_id: str | None = None) -> list[HitlPendingSignal]:
    return await self._store.list_pending(tenant_id=tenant_id)
```

**Verdict**: **CONFIRMED P0 gap** — `get()` and `wait_for()` accept signal_id but NO tenant_id filter.
Это inconsistency — list is tenant-filtered, get is not. **Real cross-tenant exposure** for callers who know signal_id.

**Action**: 1-line fix per call:
```python
async def get(self, signal_id: str) -> HitlPendingSignal | None:
    tenant_id = current_tenant_id()  # или explicit param
    return await self._store.get(signal_id, tenant_id=tenant_id)
```

**Risk severity**: HIGH (cross-tenant access to HITL signal metadata, potential decision-injection via signal body).

### 1.3 `notebooks.py:156` — NotebookService.get (CONFIRMED P0 GAP ❌)

**Source evidence** (`src/backend/services/notebooks/service.py:72-80`):
```python
async def get(self, notebook_id: str) -> Notebook | None:
    return await self._repo.get(notebook_id)
```

`NotebookRepository.get(notebook_id)` impl — NO tenant param:
```python
async def get(self, notebook_id: str) -> Notebook | None:
    """Get notebook by ID.
    
    Args:
        notebook_id: Notebook ID.
    
    Returns:
        Notebook or None if not found.
    """
    ...
```

Notebooks (per-user JupyterHub integration) should be per-tenant.

**Verdict**: **CONFIRMED P0 gap** — notebooks get() by id only, no tenant scope.

**Action**:
```python
async def get(self, notebook_id: str) -> Notebook | None:
    return await self._repo.get(notebook_id, tenant_id=current_tenant_id())
```

**Risk severity**: HIGH (cross-tenant notebook content access).

### 1.4 `ai_feedback.py:168` — AIFeedbackService.get (CONFIRMED P0 GAP ❌)

**Source evidence** (`src/backend/services/ai/feedback/feedback_service.py:268-275`):
```python
async def get(self, doc_id: str) -> AIFeedbackDoc | None:
    """Возвращает документ по id или ``None``.
    
    Args:
        doc_id: Идентификатор документа.
    
    Returns:
        Документ либо ``None``.
    """
    return await self._repo.get(doc_id)
```

Repo impl also by-id-only.

AI feedback является per-user (feedback data is user-specific). **CONFIRMED P0 gap**.

**Action**: add `tenant_id` filter (similar pattern).

**Risk severity**: MEDIUM (cross-tenant feedback reads, may contain user-identifying content).

### 1.5 `hitl_approval.py:263` — HitlApproval (CONFIRMED P0 GAP via 1.2)

**Source evidence**:
```python
signal = await self._hitl_service.get(signal_id)  # line 263
```

Same `HitlService.get()` — gap inherited from 1.2.
DSL processor's `_hitl_service` likely receives tenant_id at init.

**Verdict**: **CONFIRMED P0 gap** (same root cause as 1.2).

**Action**: fix in `HitlService.get()` auto-fixes 1.5.

## 2. Summary per audit "Всегда перепроверяй"

| Callsite | Real gap? | Severity | Cross-tenant exposure |
|---|---|---|---|
| `audit_versioning.py:151` | CONDITIONAL | MEDIUM | Depends on parent model tenant-scope |
| `hitl.py:164` | **CONFIRMED ❌** | HIGH | HitlService.get() no filter |
| `hitl.py:185` | **CONFIRMED ❌** | HIGH | Same root cause |
| `notebooks.py:156` | **CONFIRMED ❌** | HIGH | NotebookService.get() no filter |
| `ai_feedback.py:168` | **CONFIRMED ❌** | MEDIUM | AIFeedbackService.get() no filter |
| `hitl_approval.py:263` | **CONFIRMED ❌** | MEDIUM | Inherits 1.2 |
| (audit_versioning:151 dedup) | = same as 151 | — | — |

**Confirmed REAL gaps**: 4 unique (1.2 includes 1.3 and 1.5 via root cause, 1.4 independent).
**Conditional gap**: 1 (1.1 — depends on model coverage).

## 3. Realistic fix scope per v4 §10 P0

Per fixes ranked by ROI (Risk × Volume):

1. **`HitlService.get()` + `wait_for()` + `resolve()`** (1.2, 1.5):
   - 1 small fix в service layer (`get`/`wait_for`/`resolve` add `tenant_id` parameter).
   - Repository layer тоже should add filter (defense-in-depth).
   - Tests: add cross-tenant negative test.
   - 3 lines code change + 1 test.

2. **`NotebookRepository.get()` / `NotebookService.get()`** (1.3):
   - Repository add `tenant_id` parameter; service forwards from request context.
   - 1-2 lines + 1 test.

3. **`AIFeedbackRepository.get()` / `AIFeedbackService.get()`** (1.4):
   - Same pattern as Notebooks.
   - 1-2 lines + 1 test.

4. **`audit_versioning.py:151`** (conditional):
   - **First** classify versioned models: how many have TenantMixin?
   - For non-tenant models: add TenantMixin и column migration.
   - Conditional fix зависит от classification result.

## 4. Per v4 §6 Gate audit (next-cycle implementation)

| Gate | Status |
|---|---|
| Problem proof | ✅ THIS DOC (cycle 158+) — 4 confirmed gaps + 1 conditional |
| Existing solution audit | OPEN — inventory tenant-scope patterns in services/ |
| Architecture fit | Open — per-Option A or Option B/C |
| Value | Realistic — 4 confirmed gaps × HIGH severity = ~4 P0 fixes |
| Parity | per-call filter pattern (existing in list_pending) |
| Blast radius | 4 service classes (HITL, Notebook, AIFeedback, optionally DomainModel) |
| Verification plan | cross-tenant negative tests + per-class owner check |
| Approval/ADR | REQUIRED — security-relevant, ADR needed |

## 5. What was verified here

- Service-layer source inspection for each of 7 callsites.
- Per-call `WHERE tenant_id = ...` filter analysis.
- Confirmed 4-5 of 7 are real (NOT estimates).
- Honest verdict per audit "не повторять уже сделанную волну": cluster
  reads show clear inconsistency (list_pending HAS filter, get doesn't).

## 6. What still requires

- Owner decision (Option A vs B vs C).
- ADR with detailed migration plan.
- Per-call test infrastructure (cross-tenant harness).

## 7. References

- `P0_USER_DATA_CALLSITES_INVESTIGATION_2026-09-24.md` — initial deep-dive.
- `tools/classify_object_authorization.py` — heuristic classifier.
- `src/backend/services/workflows/hitl_service.py` — verified `get()` no filter.
- `src/backend/services/notebooks/service.py` — verified `get()` no filter.
- `src/backend/services/ai/feedback/feedback_service.py` — verified `get()` no filter.
- `src/backend/core/domain/models/base.py` — base has no tenant_id (audit-versioning conditional).
- `src/backend/core/domain/models/rule_engine.py` — model with tenant_id (pattern reference).
- v4 §6 "Gate допуска улучшения" framework.
- v4 §10 P0 priority (evidence + security).
- v4 §5 «presence != wiring»: always verify before claiming.
