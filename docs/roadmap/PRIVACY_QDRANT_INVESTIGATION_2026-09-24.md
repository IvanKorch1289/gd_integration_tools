# Privacy Qdrant adapter audit — cycle 158+ continuation (2026-09-24)

> **Этот документ — per-backend audit verification per v5 prompt P0 #2.**
> Per audit "Всегда перепроверяй" + v4 §3 evidence-first.

## 1. Background

Per cycle 158+ Privacy investigation:
- Redis audit + fix: closed (`82fc18a71`).
- S3 audit-verified (deferred per cycle 158+ scope).
- This doc: audit of `QdrantErasureAdapter` per audit "Всегда перепроверяй".

## 2. Source verification (`src/backend/core/privacy/delete_data_subject/_qdrant.py`)

### 2.1 Class signature

```python
class QdrantErasureAdapter:
    """Qdrant adapter — delete vectors по subject_id filter."""
    name = "qdrant"

    def __init__(self, collection_name: str = "default", client: Any = None) -> None:
        self._collection = collection_name
        self._client = client
```

### 2.2 Implementation pattern

- **`qdrant-client` dependency** (returns SKIPPED if not installed).
- **`delete` operation with `FilterSelector`** — filter by `subject_id`.
- **Async via `loop.run_in_executor`** — sync Qdrant client wrapped in executor.
- **FilterSelector** — uses `models.Filter(must=[models.FieldCondition(key="subject_id", ...)])`.

### 2.3 Per audit "Всегда перепроверяй" findings

**✅ REAL implementation exists** (NOT stub):
- Uses `qdrant_client.QdrantClient` (async via executor).
- Uses `delete(collection_name=..., points_selector=...)` with proper FilterSelector.
- Uses `models.FieldCondition(key="subject_id", ...)` for filter.
- Returns `AdapterResult` with `records_affected` count.

**❌ NOT verified per audit "не завышай":**
- ❌ **Tenant-awareness**: adapter uses `subject_id` from caller, NOT `current_tenant()` from TenantContext.
- ❌ **Per-tenant collection config**: single `collection_name` for all tenants (NOT `tenant:<id>:<collection>` pattern).
- ❌ **Pipeline wiring**: `QdrantErasureAdapter` is exported from `__init__.py`, BUT actual wiring in composition root needs verification.
- ❌ **Cross-tenant leakage**: if caller passes `subject_id` from one tenant, adapter does NOT verify caller.tenant_id matches resource.tenant_id.
- ❌ **Multiple subjects of same type**: if user + tenant both have subject_id field, no per-tenant filter.

## 3. Per audit "Всегда перепроверяй" — TenantContext integration status

| Aspect | Status |
|---|---|
| Adapter uses `subject_id` parameter | ✅ Yes (caller-provided) |
| Adapter uses `current_tenant()` from TenantContext | ❌ **No** |
| Adapter verifies caller.tenant_id matches resource.tenant_id | ❌ **No** |
| Adapter uses `tenant_id` in FilterSelector | ❌ **No** (uses `subject_id` only) |
| Per-tenant collection config | ❌ **No** (single collection for all tenants) |

**Per audit "не завышай claims"**: Adapter is **NOT tenant-aware** at the API level.
Tenant safety depends entirely on **caller's discipline** to pass correctly-scoped
`subject_id` AND use per-tenant collections in composition root.

## 4. Per audit framework — implications

Per cycle 158+ investigation + this Qdrant audit:

1. **Adapter IS real** (NOT stub) — cycle 158+ investigation's "4 adapters EXIST" confirmed.
2. **Adapter IS NOT tenant-aware** — gap remains at TENANT BOUNDARY level.
3. **Pipeline wiring needs audit** — is `QdrantErasureAdapter` actually called from
   `DeleteDataSubject.execute()` path?
4. **Per-tenant collection NOT configured** — single collection for all tenants is design risk.
5. **Contract test gap** — no per-backend contract test exists (cycle 158+
   Privacy investigation memo).

## 5. Per v4 §10 P1 + v4 §6 8-gate audit framework (next-cycle implementation)

Per audit "Movement toward end state" + "не повторять уже сделанную волну":
Qdrant fix scope:
- ❓ **Audit pipeline wiring**: is QdrantErasureAdapter called from DeleteDataSubject?
- ❓ **Add TenantContext integration**: filter by `tenant:<id>:<subject>` or per-tenant collection.
- ❓ **Per-tenant collection config**: tenant-prefixed collections (e.g., `tenant:<id>:<collection_name>`)?
- ❓ **Cross-tenant validation**: caller.tenant_id matches subject.tenant_id?
- ❓ **Contract test**: insert + erase + verify absence.

Per v4 §3 evidence-first: NOT estimates — actual measurement per audit "Всегда перепроверяй".

## 6. Per v4 §6 8-gate audit (next-cycle ADR per backend)

| Gate | Status |
|---|---|
| Problem proof | ✅ THIS DOC (cycle 158+) |
| Existing solution audit | ✅ Adapter class exists |
| Architecture fit | ✅ Matches postgresql pattern (tenant-aware per-call) |
| Value | Realistic — Qdrant stores per-user embeddings (HIGH severity) |
| Parity | Should match postgresql (tenant-aware) |
| Blast radius | 1 adapter + 1 contract test |
| Verification plan | Negative test (cross-tenant insert → erase → leak detection) |
| Approval/ADR | REQUIRED (privacy-related) |

## 7. Per cycle 158+ discipline + audit framework

Per audit + v4 + kickoff "не использовать ask_user" inverse:
- I do NOT ask user for next-cycle choice.
- This investigation memo IS the concrete progress per cycle 158+ scope.
- Qdrant fix deferred to cycle 159+ (out of current session scope).

## 8. Per audit goal audit (Privacy backends status — Qdrant specifically)

| Criterion | Status |
|---|---|
| Adapter EXISTS | ✅ **YES** (QdrantErasureAdapter class) |
| Adapter tenant-aware | ❌ NO (uses subject_id only, no TenantContext) |
| Pipeline wiring verified | ❌ NO |
| Per-tenant collection config | ❌ NO (single collection for all tenants) |
| Contract test | ❌ NO |
| Implementation deferred | ✅ YES (cycle 159+) |

## 9. References

- `PRIVACY_BACKENDS_INVESTIGATION_2026-09-24.md` (cycle 158+ broader audit).
- `PRIVACY_REDIS_INVESTIGATION_2026-09-24.md` (Redis audit, prior cycle 158+).
- `PRIVACY_S3_INVESTIGATION_2026-09-24.md` (S3 audit, prior cycle 158+).
- `src/backend/core/privacy/delete_data_subject/_qdrant.py` (per-adapter source).
- v5 prompt P0 #2 ("Privacy erasure: DeleteDataSubject покрытие; ...").
- v4 §10 P1 ("0 importers + migration window + contract test").
- v4 §5 «presence != wiring».
- v4 §3 evidence-first.
