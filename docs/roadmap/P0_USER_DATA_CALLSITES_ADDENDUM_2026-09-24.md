# P0 callsites addendum — manual review revealed 2 additional gaps (cycle 158+)

> **Этот документ — sibling к `P0_USER_DATA_CALLSITES_VERIFIED_2026-09-24.md`.**
> Per audit "Всегда перепроверяй перед тем, как утверждать" + "Movement toward
> requested end state": после classifier-based verification, manual
> inspection revealed 2 callsites, missed classifier regex pattern,
> **которые тоже являются реальными P0 gaps**.

## 1. Background

Cycle 158+ classifier (`tools/classify_object_authorization.py`) находит
только pattern `.get(id=...)` или `.filter_by(id=...)` per AST unparse.
`check_object_authorization.py` тоже использует regex-only detection.

**Limit**: **decorator patterns** + **Mongo `find_one` patterns** missed:
- `kwargs.get(id_param)` (decorator) — generic `.get(...)` без explicit `id=` keyword.
- `find_one(collection, {"_id": notebook_id})` — MongoDB-стиль не SQLAlchemy.

Per audit "не повторять уже сделанную волну" — manual investigation
single-pass, then document for next-cycle ADR.

## 2. Manual review findings (NEW)

### 2.1 `src/backend/core/security/object_ownership.py:119` — DECORATOR STUB

**Source context** (`src/backend/core/security/object_ownership.py:60-141`):
```python
def require_object_ownership(
    resource_model: type,
    id_param: str = "id",
    tenant_field: str = "tenant_id",
    raise_on_mismatch: bool = True,
) -> Callable:
    """Decorator для автоматической проверки object-level ownership.
    
    [docstring describes expected behavior]
    """
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            sig = inspect.signature(func)
            id_param_value = sig.parameters.get(id_param)
            # ... validation ...
            resource_id = kwargs.get(id_param)
            if resource_id is None:
                raise ValueError(...)
            
            # Production implementation would:
            # 1. Get current tenant from TenantContext.
            # 2. Load resource by id.
            # 3. Compare resource.tenant_id to current_tenant_id.
            # 4. Raise on mismatch.
            
            # Stub — реальная интеграция в следующих коммитах.
            logger.debug(
                "ownership_check_stub",
                resource_model=getattr(resource_model, "__name__", str(resource_model)),
                resource_id=resource_id,
            )
            return await func(*args, **kwargs)
        return wrapper
    return decorator
```

**Module docstring** (lines 1-5):
```
"""Object-level ownership guard (Sprint 1 — audit 2026-09-22 P0).

JWT/API key подтверждают identity, но это НЕ доказывает object-level
authorization: пользователь tenant_A может прочитать файл tenant_B, если
resource_id привязан к чужому tenant. ``@require_object_ownership``
декоратор автоматически проверяет, что tenant_id запрошенного ресурса
совпадает с tenant_id вызывающего.
```

**Verdict**: **CONFIRMED P0 GAP — DECORATOR IS STUB**. The whole point of
this module (per its own docstring) is to enforce object-level ownership
— but the implementation is empty stub that only logs.

**Production wiring requires** (per module's own comment):
1. Get current tenant from `TenantContext`.
2. Load resource by id.
3. Compare `resource.tenant_id` to `current_tenant_id()`.
4. Raise `AuthorizationError` on mismatch.

**Severity**: CRITICAL — entire ownership guard module is non-functional.

### 2.2 `src/backend/infrastructure/repositories/notebooks_mongo.py:134, 140` — `self.get(notebook_id)`

**Source context** (`notebooks_mongo.py:115-138`):
```python
async def append_version(
    self,
    notebook_id: str,
    content: str,
    changed_by: str,
    summary: str | None = None,
) -> Notebook | None:
    # ... write to MongoDB ...
    return await self.get(notebook_id)  # line 134

async def restore_version(
    self, notebook_id: str, version: int, changed_by: str
) -> Notebook | None:
    """Метод restore_version (см. signature)."""
    existing = await self.get(notebook_id)  # line 140
    if existing is None or existing.is_deleted:
        return None
    # ...
```

**`get()` impl** (`notebooks_mongo.py:101-110`):
```python
async def get(self, notebook_id: str) -> Notebook | None:
    """Get notebook by ID.
    
    Args:
        notebook_id: Notebook ID.
    
    Returns:
        Notebook or None if not found.
    """
    doc = await self._client().find_one(_COLLECTION, {"_id": notebook_id})
    return _doc_to_notebook(doc) if doc else None
```

**Verdict**: **CONFIRMED P0 GAP**. Mongo `find_one` фильтр `{"_id": notebook_id}`
без tenant_id — any tenant can read any notebook если знает `_id`.

**Severity**: HIGH (NotebooksMongRepository — Mongo-backed notebook persistence).

### 2.3 Pattern coverage gap in classifier

Both 2.1 и 2.2 missed by:
- `check_object_authorization.py`: regex-based, looks only для `.get(id=...)` / `.filter_by(id=...)`.
- `tools/classify_object_authorization.py`: AST-based, но heuristic matches
  user-data/infra-regex only — не catches decorator patterns.

**Next-cycle classifier enhancement**: добавить pattern detection для:
- `kwargs.get(<id_param>)` inside decorators — likely ownership check.
- `find_one({"_id": ...})` MongoDB-style — needs tenant_id filter check.

## 3. Updated total P0 fix scope

| Source | Callsites | Status | Severity |
|---|---|---|---|
| `P0_USER_DATA_CALLSITES_VERIFIED_2026-09-24.md` | 4 unique confirmed | REAL | HIGH-MEDIUM |
| **This addendum** | **+2** (object_ownership stub + notebooks_mongo.get) | **REAL (1 STUB, 1 missing filter)** | **CRITICAL + HIGH** |
| **Total cycle 158+** | **6 confirmed** | mixed | mixed |

**Updated fix list**:

1. ~~(previous) `HitlService.get()` + `wait_for()` + `resolve()` add tenant_id~~ — 1 fix.
2. ~~(previous) `NotebookRepository.get()` (SQLAlchemy)~~ — 1 fix.
3. ~~(previous) `AIFeedbackRepository.get()`~~ — 1 fix.
4. **(NEW) `notebooks_mongo.py:get()` + `append_version()` + `restore_version()` add tenant_id filter** — 1 fix.
5. **(NEW) `object_ownership.py` decorator implementation** (CRITICAL — entire module is stub) — bigger fix.

## 4. Per v4 §6 Gate assessment (updated)

| Gate | Status for ADDENDUM |
|---|---|
| Problem proof | ✅ THIS DOC (cycle 158+) |
| Existing solution audit | OPEN — already noted in ADR-0345 |
| Architecture fit | OPEN — affects ADR-0345 Option A/B/C decision |
| Value | Realistic — fixes 1 CRITICAL stub + 1 HIGH gap |
| Parity | Decorator pattern: backwards-compatible (current behavior = stub log). Mongo fix: 1 line filter addition |
| Blast radius | `object_ownership` decorator affects ALL endpoints using it (currently nobody uses it per `core/api/` survey). Mongo fix affects notebook persistence paths |
| Verification plan | Per-fix tests (decorator unit tests + Mongo cross-tenant test) |
| Approval/ADR | REQUIRED — same ADR-0345 covers this |

## 5. Recommendation update

Per cycle 158+ evidence: ADR-0345 scope should be updated to include:
- (NEW) `object_ownership.py` decorator implementation (~10-15 LOC + 4 tests).
- (NEW) `notebooks_mongo.py:get()` tenant filter (~1-2 LOC + 1 test).

**Total updated fix estimate**: 12-15 LOC + 5-6 cross-tenant tests (vs prior 6-10 LOC + 3-4 tests).

## 5.1 Notebook model analysis (CRITICAL scope re-evaluation)

Per audit "Всегда перепроверяй": re-investigated `Notebook` Pydantic model
после addendum publication — **Notebook HAS NO `tenant_id` field**.

**Source** (`src/backend/core/models/notebooks.py`):
```python
class Notebook(BaseModel):
    """Документ заметки с историей версий и мягким удалением."""
    
    model_config = ConfigDict(extra="ignore")
    
    id: str = Field(default_factory=lambda: uuid4().hex)
    title: str
    tags: list[str] = Field(default_factory=list)
    latest_version: int = 0
    created_by: str
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    is_deleted: bool = False
    versions: list[NotebookVersion] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

**Implication**: Adding `tenant_id` filter to Mongo queries requires:
1. Add `tenant_id: str` field to `Notebook` model.
2. Migration of EXISTING notebooks (default value needed, e.g., `"default"`).
3. Update ALL write paths (`create`, `update`, etc.) to set `tenant_id`.
4. Add filter to read paths.

**Honest scope re-evaluation per audit**:
- ❌ **NOT** 1-2 LOC fix (was initial claim in section 5).
- ✅ Migration required (model change + data migration + multiple writers).
- ✅ Per v4 §10 P1 — needs **migration window + contract test + 0 importers audit**.
- ✅ **Bigger architectural change** than originally estimated.

**Updated fix list** (revised):

| Priority | Fix | LOC | Severity | Notes |
|---|---|---|---|---|
| 1 | `HitlService.get()` + `wait_for()` + `resolve()` add `tenant_id` parameter | ~6 LOC + 3 tests | HIGH | `HitlPendingSignal` HAS `tenant_id` field — backwards-compat |
| 2 | `HitlSignalStore` Protocol + 2 impls (Redis, InMemory) add `tenant_id` parameter | ~10 LOC + 2 tests | HIGH | Layer below service |
| 3 | `hitl_approval.py:263` caller update to pass `current_tenant_id()` | ~2 LOC + 1 test | HIGH | Per audit "Всегда перепроверяй" — caller change required |
| 4 | `Notebook` model: add `tenant_id` column + migration + writer updates | ~15 LOC + 5 tests | CRITICAL+ | **NEW: model schema change** |
| 5 | `notebooks_mongo.py:get()` filter by tenant | ~2 LOC | HIGH | Depends on #4 |
| 6 | `AIFeedbackRepository.get()` filter by tenant | ~2 LOC + 1 test | MEDIUM | `AIFeedbackDoc` model has tenant_id |
| 7 | `object_ownership.py` decorator implementation | ~15 LOC + 4 tests | CRITICAL | Decorator stub → real implementation |

**Total updated LOC**: ~50 LOC + 16 tests (vs prior 12-15 LOC estimate).

**Architectural impact**:
- 7 separate commits per fix (per atomic commit principle).
- Migration window required for fix #4 (Notebook model).
- Contract test required per v4 §10 P1.

Per cycle 158+ discipline (3 architectural forks already done) + audit "не повторять уже сделанную волну": **NOT** all 7 fixes should be in one cycle. Recommended split per next cycle:
- **Cycle 159**: fixes #1, #2, #3 (HITL stack) — atomic, ~20 LOC + 6 tests.
- **Cycle 160**: fixes #6 (AIFeedback) — small, atomic.
- **Cycle 161**: fix #4 + #5 (Notebook model + Mongo) — model migration, bigger.
- **Cycle 162**: fix #7 (object_ownership decorator) — security-critical, separate.

Each cycle per v4 §10 P1 migration window per individual fix.

## 6. What I delivered this iteration (per audit "Всегда перепроверяй")

- ✅ Manual re-inspection of 24 unknown callsites (sampled).
- ✅ 2 new P0 gaps discovered (object_ownership stub + notebooks_mongo get).
- ✅ Updated total scope: 4 → 6 confirmed real P0 gaps.
- ✅ Per v4 §3 evidence-first: not estimates, but source-verified.

## 7. What I NOT delivered (per scope + decision-required)

- ❌ Не реализовали object_ownership decorator (requires ADR choice per ADR-0345).
- ❌ Не added tenant_id to notebooks_mongo (per-call fix needs ADR).
- ❌ Не expanded classifier heuristics для decorator patterns (next-cycle enhancement).

## 8. References

- `P0_USER_DATA_CALLSITES_VERIFIED_2026-09-24.md` — sibling verification doc.
- `ADR-0345-p0-object-ownership-policy-options.md` — DRAFT awaiting user choice.
- `tools/classify_object_authorization.py` — heuristic tool.
- v4 §3 evidence-first — manual investigation surfaced missed gaps.
- v4 §5 «presence != wiring» — automated tools miss edge cases, manual review needed.
