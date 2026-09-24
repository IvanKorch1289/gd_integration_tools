# Privacy backends investigation — cycle 158+ continuation (2026-09-24)

> **Этот документ — investigation memo per v5 prompt P0 #2 (Privacy erasure).**
> Per audit "Всегда перепроверяй" + v4 §3 evidence-first:
> прямой measurement vs estimates.

## 1. Background

Per `tools/checks/check_privacy_lifecycle.py` (current state, 2026-09-24):

```
Storage coverage: 1/5 backends have erasure
  - postgres: ✅
  - redis: ❌ no delete API used
  - s3: ❌ no delete_object API used
  - qdrant: ❌ no subject-specific vector delete
  - ai_memory: ❌ no delete in LangMem

Issues:
  ❌ Storage backends without erasure coverage: redis, s3, qdrant, ai_memory
```

Per audit + v4 §3 — verify claim BEFORE acting on it.

## 2. Actual implementation status (audit-verified)

Per `wc -l` measurement + class name inspection:

| Backend | Module LOC | Class | Real impl status |
|---|---|---|---|
| `_postgres.py` | 62 LOC | (PG-backed) | ✅ Full erase (per gate) |
| `_redis.py` | 102 LOC | `RedisErasureAdapter` | EXISTS but gate doesn't recognize |
| `_s3.py` | 117 LOC | `S3ErasureAdapter` | EXISTS but gate doesn't recognize |
| `_qdrant.py` | 122 LOC | (Qdrant adapter) | EXISTS but gate doesn't recognize |
| `_langmem.py` | 94 LOC | (LangMem adapter) | EXISTS but gate doesn't recognize |

**Per audit "Всегда перепроверяй"**: **4 erasure adapters EXIST in code**. The gate's static
string-matching heuristic does NOT recognize them.

## 3. Gate logic analysis (per audit "не завышай claims")

`check_privacy_lifecycle.py` uses static string-matching:
- `redis`: check for `delete_object` API used somewhere in code.
- `s3`: same pattern.
- `qdrant`: file has both "delete" + ("filter" OR "subject_id").
- `ai_memory`: file has "delete" in LangMem path.

**Per v4 §5 «presence != wiring»**: presence of `class RedisErasureAdapter`
≠ "actually used in production pipeline". The static heuristic may give
**false negatives** (adapter exists but not wired) AND **false positives**
(adapter exists but not really tenant-aware).

## 4. Per-backend audit findings

### 4.1 Redis — `RedisErasureAdapter` (per src/core/privacy/delete_data_subject/_redis.py)

- ✅ Class exists.
- ❓ Implementation: SCAN + UNLINK for subject-related cache keys.
- ❓ **NOT audited**: does it use `current_tenant()` from TenantContext?
- ❓ **NOT audited**: is this adapter wired into DataSubjectEraser pipeline?

### 4.2 S3 — `S3ErasureAdapter` (per src/core/privacy/delete_data_subject/_s3.py)

- ✅ Class exists.
- ❓ Implementation: delete objects + versions.
- ❓ **NOT audited**: tenant-aware filter?
- ❓ **NOT audited**: wired into pipeline?

### 4.3 Qdrant — adapter (per _qdrant.py)

- ✅ Class exists (122 LOC).
- ❓ **NOT audited**: tenant-aware delete?
- ❓ **NOT audited**: wired into pipeline?

### 4.4 LangMem (ai_memory) — adapter (per _langmem.py)

- ✅ Class exists (94 LOC).
- ❓ **NOT audited**: per-tenant namespace wipe?
- ❓ **NOT audited**: wired into pipeline?

## 5. Per audit "Всегда перепроверяй" — honest scope

**Original gate claim**: "1/5 backends have erasure" (redis/s3/qdrant/ai_memory lack).

**Audit-verified reality** (per code inspection):
- **4 erasure adapter classes EXIST** in code.
- Gate's static heuristic doesn't recognize them.
- Actual wiring + tenant-awareness NOT yet verified.

**Per v4 §3 evidence-first**: NOT 0% coverage. Actual = 4 of 5 adapters exist,
but possibly 0 are wired + tenant-aware.

## 6. Per v4 §10 P1 + cycle 158+ discipline — next-cycle implementation

For each backend (Redis/S3/Qdrant/ai_memory):

1. **Audit tenant-awareness**: does adapter use `current_tenant()` from TenantContext?
2. **Audit pipeline wiring**: is adapter called from DataSubjectEraser?
3. **Fix per audit**: if exists but not wired → wire it. If not tenant-aware → add.
4. **Per-backend negative test**: insert data, erase, verify absence.
5. **Gate update**: check_privacy_lifecycle should detect actual wiring (not
   static heuristic). Move to runtime probe or import-graph inspection.

## 7. Per v4 §6 8-gate audit (next-cycle ADR per backend)

Per backend (4 × similar analysis):

| Gate | Status |
|---|---|
| Problem proof | ✅ THIS DOC (cycle 158+) |
| Existing solution audit | OPEN — adapter code inspection needed |
| Architecture fit | ✅ matches postgresql pattern |
| Value | Realistic — 4 backends × HIGH severity |
| Parity | Should match postgresql |
| Blast radius | 4 adapters + tests |
| Verification plan | Per-backend negative tests |
| Approval/ADR | REQUIRED (privacy-related) |

## 8. Per cycle 158+ discipline + audit framework

Per audit + v4 + kickoff "не использовать ask_user" inverse:
- I do NOT ask user for next-cycle direction.
- This investigation memo IS the concrete progress per cycle 158+ scope.
- Privacy backends implementation deferred to cycle 159+ (out of current session scope).

## 9. Per audit goal audit (Privacy backends status)

| Criterion | Status |
|---|---|
| Completion of Privacy backends | ❌ NO (audit phase complete, implementation deferred) |
| Blocked threshold met | ❌ NO |
| Movement toward end state | ✅ YES (audit-verified 4 adapters exist, gate static heuristic inaccurate) |
| Goal status | remains **ACTIVE** |

## 10. References

- `tools/checks/check_privacy_lifecycle.py` (current gate, static heuristic).
- `src/backend/core/privacy/delete_data_subject/_*.py` (5 backend modules).
- v4 §10 P1 ("Удалять shim только после 0 importers + migration window + contract test").
- v5 prompt P0 #2 ("Privacy erasure: DeleteDataSubject покрытие; ...").
- cycle 158+ PROGRESS_LEDGER §2 (Privacy orchestration — P1 audit debt).

## 11. Что NOT в этом commit (per v4 §3 + audit)

- ❌ Не имплементировал Privacy backends erasure (out of cycle 158+ scope).
- ❌ Не rewrote `check_privacy_lifecycle.py` для runtime probe.
- ❌ Не ADR'd per-backend implementation (deferred to cycle 159+).
