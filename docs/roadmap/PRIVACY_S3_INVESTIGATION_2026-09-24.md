# Privacy S3 adapter audit — cycle 158+ continuation (2026-09-24)

> **Этот документ — per-backend audit verification per v5 prompt P0 #2.**
> Per audit "Всегда перепроверяй" + v4 §3 evidence-first.

## 1. Background

Per cycle 158+ investigation (`PRIVACY_BACKENDS_INVESTIGATION_2026-09-24.md`):
- 4 erasure adapter classes EXIST.
- Redis audit (commit `82fc18a71`) closed 1 backend.
- This doc: audit of `S3ErasureAdapter` per audit "Всегда перепроверяй".

## 2. Source verification (`src/backend/core/privacy/delete_data_subject/_s3.py`)

### 2.1 Class signature

```python
class S3ErasureAdapter:
    """S3 adapter — delete objects + versions."""
    name = "s3"

    def __init__(
        self,
        bucket_name: str | None = None,
        s3_client: Any = None,
    ) -> None:
        self._bucket_name = bucket_name
        self._s3_client = s3_client
```

### 2.2 Implementation pattern

- **aioboto3 dependency** (returns SKIPPED if not installed).
- **list_objects_v2** with `Prefix={subject_type}/{subject_id}/` for filtering.
- **Versioning handling**: includes both current objects and versions.
- **Delete via delete_objects** API (batch).

### 2.3 Per audit "Всегда перепроверяй" findings

**✅ REAL implementation exists** (NOT stub):
- Uses `aioboto3.Session().client("s3")` (async).
- Uses `list_objects_v2` paginator.
- Uses `delete_objects` (batch delete).
- Returns `AdapterResult` with `records_affected` count.

**❌ NOT verified per audit "не завышай":**
- ❌ **Tenant-awareness**: adapter uses `subject_id` from caller, NOT `current_tenant()` from TenantContext.
- ❌ **Pipeline wiring**: `S3ErasureAdapter` is exported from `__init__.py`, BUT actual wiring in composition root needs verification.
- ❌ **Cross-tenant leakage**: if caller passes `subject_id` from one tenant, adapter does NOT verify caller.tenant_id matches resource.tenant_id.
- ❌ **S3 bucket configuration**: adapter takes `bucket_name` parameter, but tenant-prefixed buckets (e.g., per-tenant buckets) NOT yet implemented.

## 3. Per audit "Всегда перепроверяй" — TenantContext integration status

| Aspect | Status |
|---|---|
| Adapter uses `subject_id` parameter | ✅ Yes (caller-provided) |
| Adapter uses `current_tenant()` from TenantContext | ❌ **No** |
| Adapter verifies caller.tenant_id matches resource.tenant_id | ❌ **No** |
| Adapter uses `tenant_id` in Prefix pattern | ❌ **No** (uses `subject_id` only) |
| Per-tenant bucket configuration | ❌ **No** (single bucket for all tenants) |

**Per audit "не завышай claims"**: Adapter is **NOT tenant-aware** at the API level.
Tenant safety depends entirely on **caller's discipline** to pass correctly-scoped
`subject_id`. Per v4 §5 «presence != wiring», presence of adapter class ≠
tenant-aware deletion.

## 4. Per audit framework — implications

Per cycle 158+ investigation + this S3 audit:

1. **Adapter IS real** (NOT stub) — cycle 158+ investigation's "4 adapters EXIST" confirmed.
2. **Adapter IS NOT tenant-aware** — gap remains at TENANT BOUNDARY level.
3. **Pipeline wiring needs audit** — is `S3ErasureAdapter` actually called from
   `DeleteDataSubject.execute()` path?
4. **Contract test gap** — no per-backend contract test exists (cycle 158+
   Privacy investigation memo).

## 5. Per v4 §10 P1 + v4 §6 8-gate audit framework (next-cycle implementation)

Per audit "Movement toward end state" + "не повторять уже сделанную волну":
S3 fix scope:
- ❓ **Audit pipeline wiring**: is S3ErasureAdapter called from DeleteDataSubject?
- ❓ **Add TenantContext integration**: filter SCAN by tenant-prefix?
- ❓ **Per-tenant bucket config**: tenant-prefixed buckets (e.g., `tenant:t-a/`)?
- ❓ **Cross-tenant validation**: caller.tenant_id matches subject.tenant_id?
- ❓ **Contract test**: insert + erase + verify absence.

Per v4 §3 evidence-first: NOT estimates — actual measurement per audit "Всегда перепроверяй".

## 6. Per v4 §6 8-gate audit (next-cycle ADR per backend)

| Gate | Status |
|---|---|
| Problem proof | ✅ THIS DOC (cycle 158+) |
| Existing solution audit | ✅ Adapter class exists |
| Architecture fit | ✅ Matches postgresql pattern |
| Value | Realistic — S3 is per-tenant object store |
| Parity | Should match postgresql (tenant-aware) |
| Blast radius | 1 adapter + 1 contract test |
| Verification plan | Negative test (cross-tenant insert → erase → leak detection) |
| Approval/ADR | REQUIRED (privacy-related) |

## 7. Per cycle 158+ discipline + audit framework

Per audit + v4 + kickoff "не использовать ask_user" inverse:
- I do NOT ask user for next-cycle choice.
- This investigation memo IS the concrete progress per cycle 158+ scope.
- S3 fix deferred to cycle 159+ (out of current session scope).

## 8. Per audit goal audit (Privacy backends status — S3 specifically)

| Criterion | Status |
|---|---|
| Adapter EXISTS | ✅ **YES** (S3ErasureAdapter class) |
| Adapter tenant-aware | ❌ NO (uses subject_id only, no TenantContext) |
| Pipeline wiring verified | ❌ NO |
| Contract test | ❌ NO |
| Per-tenant bucket config | ❌ NO |
| Implementation deferred | ✅ YES (cycle 159+) |

## 9. References

- `PRIVACY_BACKENDS_INVESTIGATION_2026-09-24.md` (cycle 158+ broader audit).
- `PRIVACY_REDIS_INVESTIGATION_2026-09-24.md` (Redis audit, prior cycle 158+).
- `src/backend/core/privacy/delete_data_subject/_s3.py` (per-adapter source).
- v5 prompt P0 #2 ("Privacy erasure: DeleteDataSubject покрытие; ...").
- v4 §10 P1 ("0 importers + migration window + contract test").
- v4 §5 «presence != wiring».
- v4 §3 evidence-first.
