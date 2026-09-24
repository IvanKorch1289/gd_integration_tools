# Privacy Postgres adapter audit — cycle 158+ continuation (2026-09-24)

> **Этот документ — per-backend audit verification per v5 prompt P0 #2.**
> Per audit "Всегда перепроверяй" + v4 §3 evidence-first.

## 1. Background

Per cycle 158+ Privacy investigation:
- Redis closed (`82fc18a71`).
- S3 + Qdrant + Langmem audits completed (3 backends audit-verified).
- **Postgres audit** — 5 of 5 Privacy backends, final one.

## 2. Source verification (`src/backend/core/privacy/delete_data_subject/_postgres.py`)

### 2.1 Adapter signature

```python
class PostgresErasureAdapter:
    """PostgreSQL adapter — DELETE/anonymize в основной БД (Sprint 1 stub)."""
    name = "postgresql"

    def __init__(self, session_factory: Callable | None = None) -> None:
        self._session_factory = session_factory

    async def execute(
        self,
        subject_id: str,
        subject_type: str,
        strategy: ErasureStrategy,
        correlation_id: str,
    ) -> AdapterResult:
        """Execute erasure в PostgreSQL."""
        start = time.monotonic()
        try:
            await asyncio.sleep(0)
            duration = (time.monotonic() - start) * 1000
            return AdapterResult(
                adapter_name=self.name,
                status=ErasureResultStatus.SUCCESS,
                duration_ms=duration,
                records_affected=0,  # stub
            )
        ...
```

### 2.2 Per audit "Всегда перепроверяй" — KEY FINDING

**⚠️ Postgres adapter is a STUB** — per source code inspection:

- Module docstring (line 4): "Stub-implementation: реальная DELETE/anonymize логика будет добавлена в Sprint 4+ (требует tenant-aware queries)."
- Class docstring (line 25): "PostgreSQL adapter — DELETE/anonymize в основной БД (Sprint 1 stub)."
- `execute()` body (lines 44-52):
  ```python
  await asyncio.sleep(0)  # only sleeps!
  return AdapterResult(
      adapter_name=self.name,
      status=ErasureResultStatus.SUCCESS,  # returns SUCCESS
      duration_ms=duration,
      records_affected=0,  # stub
  )
  ```

**✅ REAL implementation** = **NO** — only `asyncio.sleep(0)` then returns SUCCESS.
**⚠️ Adapter EXISTS but DOES NOTHING** — per audit + v4 §5 "presence != wiring".

### 2.3 Per audit + v4 §3 evidence-first — implications

Per audit "не повторять уже сделанную волну" + v4 §3:
- ❌ **Postgres adapter is a STUB** — `records_affected=0` always.
- ❌ **Cross-tenant leakage** — adapter claims SUCCESS but deletes nothing.
- ❌ **Privacy posture** — Postgres (the primary database!) has no actual erasure logic.
- ❌ **Module docstring admits it**: "реальная DELETE/anonymize логика будет добавлена в Sprint 4+".

This is **the most severe finding** in cycle 158+ Privacy backends audit:

- Redis: real but NOT tenant-aware (fixed `82fc18a71`).
- S3: real but NOT tenant-aware (deferred).
- Qdrant: real but NOT tenant-aware (deferred).
- Langmem: real but NOT tenant-aware (deferred).
- **Postgres: STUB (no real implementation at all)** — MOST severe.

## 3. Per audit "Всегда перепроверяй" — TenantContext integration status

| Aspect | Status |
|---|---|---|
| Adapter EXISTS in code | ✅ YES (class definition) |
| Adapter IS real implementation | ❌ **NO** — only `asyncio.sleep(0)` |
| Adapter uses `subject_id` filter | ❌ NO (only sleep) |
| Adapter uses `current_tenant()` from TenantContext | ❌ NO |
| Adapter uses `tenant_id` filter | ❌ **NO** (no filter at all) |
| Pipeline wiring verified | ❌ NO |
| Contract test | ❌ NO |
| Privacy posture | ❌ **CRITICAL** (no actual erasure) |

## 4. Per audit framework — implications

Per cycle 158+ investigation + this Postgres audit:

1. **Adapter is a STUB** — most severe finding in Privacy backends audit.
2. **Privacy posture for PRIMARY database is critical** — primary user data store has no actual erasure logic.
3. **Module docstring admits it**: "Stub-implementation" + "Sprint 1 stub".
4. **Module docstring claims future work**: "реальная DELETE/anonymize логика будет добавлена в Sprint 4+".

## 5. Per v4 §10 P1 + v4 §6 8-gate audit framework (next-cycle implementation)

Per audit + v4 §3 evidence-first + v5 prompt — REAL implementation candidate:

### Option A — implement real Postgres erasure

**Diff** (`_postgres.py`):
```python
async def execute(
    self,
    subject_id: str,
    subject_type: str,
    strategy: ErasureStrategy,
    correlation_id: str,
    *,
    explicit_tenant_id: str | None = None,
) -> AdapterResult:
    # Per audit + v4 §3 evidence-first — Postgres is PRIMARY DB.
    # Per v5 prompt P0 #2: tenant-awareness via current_tenant().
    start = time.monotonic()
    try:
        from src.backend.core.tenancy import get_tenant_id

        effective_tenant = (
            explicit_tenant_id if explicit_tenant_id is not None
            else get_tenant_id()
        )

        session_factory = self._session_factory
        if session_factory is None:
            return AdapterResult(
                adapter_name=self.name,
                status=ErasureResultStatus.SKIPPED,
                duration_ms=(time.monotonic() - start) * 1000,
                error="session_factory not configured",
            )

        async with session_factory() as session:
            # Per audit: BOTH subject_id AND tenant filter required.
            conditions = [subject_model.subject_id == subject_id]
            if effective_tenant:
                conditions.append(subject_model.tenant_id == effective_tenant)

            await session.execute(
                delete(subject_model).where(*conditions)
            )
            await session.commit()

        duration = (time.monotonic() - start) * 1000
        return AdapterResult(
            adapter_name=self.name,
            status=ErasureResultStatus.SUCCESS,
            duration_ms=duration,
            records_affected=<actual_count>,
        )
    except Exception as exc:
        ...
```

### Per v4 §6 8-gate audit

| Gate | Status |
|---|---|
| Problem proof | ✅ THIS DOC (cycle 158+) — REAL stub + privacy posture |
| Existing solution audit | ✅ Adapter class exists (but STUB) |
| Architecture fit | ✅ Matches Option A pattern (Redis/S3/Qdrant) |
| Value | **CRITICAL** — Postgres is PRIMARY DB |
| Parity | Should match postgresql (tenant-aware) |
| Blast radius | 1 adapter + 1 contract test |
| Verification plan | Negative test (cross-tenant insert → erase → leak detection) |
| Approval/ADR | REQUIRED (privacy-critical) |

## 6. Per audit + cycle 158+ discipline + v4 §11

Per audit + cycle 158+ discipline "не повторять уже сделанную волну" + v4 §11:
- ✅ Postgres audit IS new concrete progress per cycle 158+ scope.
- ✅ **MOST SEVERE finding** in Privacy backends audit (Postgres is PRIMARY DB).
- ❌ Postgres implementation deferred per cycle 158+ scope + audit discipline.

## 7. Per audit goal audit (Privacy backends status — Postgres specifically)

| Criterion | Status |
|---|---|
| Adapter EXISTS in code | ✅ YES (class definition) |
| Adapter IS real implementation | ❌ **NO** (only `asyncio.sleep(0)`) |
| Adapter uses `subject_id` filter | ❌ NO (no filter) |
| Privacy posture | ❌ **CRITICAL** (PRIMARY DB has no erasure logic) |
| Pipeline wiring verified | ❌ NO |
| Contract test | ❌ NO |
| Implementation deferred | ✅ YES (cycle 159+ — critical priority) |

## 8. References

- `PRIVACY_BACKENDS_INVESTIGATION_2026-09-24.md` (cycle 158+ broader audit).
- `PRIVACY_REDIS_INVESTIGATION_2026-09-24.md` (Redis audit, prior cycle 158+).
- `PRIVACY_S3_INVESTIGATION_2026-09-24.md` (S3 audit, prior cycle 158+).
- `PRIVACY_QDRANT_INVESTIGATION_2026-09-24.md` (Qdrant audit, prior cycle 158+).
- `PRIVACY_LANGMEM_INVESTIGATION_2026-09-24.md` (Langmem audit, prior cycle 158+).
- `src/backend/core/privacy/delete_data_subject/_postgres.py` (per-adapter source).
- v5 prompt P0 #2 ("Privacy erasure: DeleteDataSubject покрытие; ...").
- v4 §10 P1 ("0 importers + migration window + contract test").
- v4 §5 «presence != wiring».
- v4 §3 evidence-first.
