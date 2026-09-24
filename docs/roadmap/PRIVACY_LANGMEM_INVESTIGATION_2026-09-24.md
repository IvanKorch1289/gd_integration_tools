# Privacy Langmem adapter audit — cycle 158+ continuation (2026-09-24)

> **Этот документ — per-backend audit verification per v5 prompt P0 #2.**
> Per audit "Всегда перепроверяй" + v4 §3 evidence-first.

## 1. Background

Per cycle 158+ Privacy investigation:
- Redis closed (`82fc18a71`).
- S3 + Qdrant + Langmem + Postgres audits (4 backends, this doc covers Langmem).
- This doc: Langmem audit per audit "Всегда перепроверяй".

## 2. Source verification

### 2.1 Adapter (`src/backend/core/privacy/delete_data_subject/_langmem.py`)

```python
async def execute(
    self,
    subject_id: str,
    subject_type: str,
    strategy: ErasureStrategy,
    correlation_id: str,
) -> AdapterResult:
    start = time.monotonic()
    try:
        from src.backend.core.domain.models.langmem_models import (
            LangMemEpisodic,
            LangMemProcedural,
        )
        # ...
        epi_q = delete(LangMemEpisodic).where(
            LangMemEpisodic.subject_id == subject_id
        )
        proc_q = delete(LangMemProcedural).where(
            LangMemProcedural.subject_id == subject_id
        )
        # ...
```

### 2.2 Models (`src/backend/core/domain/models/langmem_models.py`)

**`LangMemEpisodic`** (lines 29-47):
```python
class LangMemEpisodic(Base):
    """Эпизод (диалог / событие) с временной привязкой."""
    __tablename__ = "langmem_episodic"

    id: Mapped[int]
    session_id: Mapped[str]
    tenant: Mapped[str | None]  # ← TENANT FIELD!
    role: Mapped[str]
    content: Mapped[str]
    meta: Mapped[dict | None]
    occurred_at: Mapped[datetime]

    __table_args__ = (
        Index("ix_langmem_episodic_session_time", "session_id", "occurred_at"),
        Index("ix_langmem_episodic_tenant", "tenant"),  # ← INDEX on tenant!
    )
```

**`LangMemProcedural`** (lines 50+): SAME structure — has `tenant: Mapped[str | None]` + index on tenant.

### 2.3 Per audit "Всегда перепроверяй" — KEY FINDING

**✅ Models HAVE `tenant` column** — per-source inspection (`grep -n "tenant"`):
```
29:class LangMemEpisodic(Base):
36:    tenant: Mapped[str | None] = mapped_column(String(128), nullable=True)
46:        Index("ix_langmem_episodic_tenant", "tenant"),
50:class LangMemProcedural(Base):
57:    tenant: Mapped[str | None] = mapped_column(String(128), nullable=True)
```

**❌ Adapter filter DOES NOT use `tenant` column** — per-source inspection:
```
epi_q = delete(LangMemEpisodic).where(
    LangMemEpisodic.subject_id == subject_id  # ← ONLY subject_id!
)
```

**This is a REAL cross-tenant exposure** (per audit + v4 §5):
- If `subject_id` is globally unique OR attacker knows another tenant's `subject_id`,
- Adapter deletes records matching ONLY `subject_id` regardless of `tenant`.
- Cross-tenant data loss possible.

## 3. Per audit "Всегда перепроверяй" — TenantContext integration status

| Aspect | Status |
|---|---|
| Adapter uses `subject_id` parameter | ✅ Yes |
| Models HAVE `tenant` column | ✅ **YES** |
| Models HAVE index on `tenant` | ✅ **YES** |
| Adapter uses `current_tenant()` from TenantContext | ❌ **NO** |
| Adapter filter includes `tenant_id == current_tenant()` | ❌ **NO** |
| Pipeline wiring verified | ❌ NO |
| Contract test | ❌ NO |

## 4. Per audit framework — implications

Per cycle 158+ investigation + this Langmem audit:

1. **Adapter IS real** (NOT stub).
2. **Models HAVE `tenant` column + index** — design supports tenant-scoping.
3. **Adapter filter is INCOMPLETE** — only uses `subject_id`, missing `tenant` check.
4. **Real cross-tenant exposure** — per audit "не завышай" — this IS a real issue.

## 5. Per audit + v4 §3 evidence-first + v5 prompt P0 #2 — REAL FIX CANDIDATE

Per audit + cycle 158+ discipline + v4 §6 8-gate audit framework:

### Option A candidate — add `tenant` filter

**Diff** (`_langmem.py`):
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
    # ... existing imports ...
    
    from src.backend.core.tenancy import get_tenant_id
    effective_tenant = (
        explicit_tenant_id if explicit_tenant_id is not None
        else get_tenant_id()
    )
    
    # Build filters with BOTH subject_id AND tenant.
    epi_filters = [LangMemEpisodic.subject_id == subject_id]
    proc_filters = [LangMemProcedural.subject_id == subject_id]
    if effective_tenant:
        epi_filters.append(LangMemEpisodic.tenant == effective_tenant)
        proc_filters.append(LangMemProcedural.tenant == effective_tenant)
    
    epi_q = delete(LangMemEpisodic).where(*epi_filters)
    proc_q = delete(LangMemProcedural).where(*proc_filters)
```

### Per v4 §6 8-gate audit

| Gate | Status |
|---|---|
| Problem proof | ✅ THIS DOC (cycle 158+) — REAL cross-tenant exposure verified |
| Existing solution audit | ✅ Models HAVE `tenant` column (design supports fix) |
| Architecture fit | ✅ Matches Option A pattern (Redis/S3/Qdrant) |
| Value | Realistic — LangMem stores per-user AI memory (HIGH severity) |
| Parity | Should match postgresql (tenant-aware) |
| Blast radius | 1 adapter + 1 contract test |
| Verification plan | Negative test (cross-tenant insert → erase → leak detection) |
| Approval/ADR | REQUIRED (privacy-related) |

## 6. Per audit + cycle 158+ discipline + v4 §11

Per audit + cycle 158+ discipline "не повторять уже сделанную волну" + v4 §11:
- ✅ Langmem audit IS new concrete progress per cycle 158+ scope.
- ✅ Langmem fix candidate IS actionable (models support fix).
- ❌ Langmem implementation deferred per cycle 158+ scope + audit discipline.

## 7. Per audit goal audit (Privacy backends status — Langmem specifically)

| Criterion | Status |
|---|---|
| Adapter EXISTS | ✅ **YES** (LangMemErasureAdapter class) |
| Models HAVE `tenant` column | ✅ **YES** (audit-verified) |
| Adapter uses `tenant` filter | ❌ **NO** (REAL cross-tenant exposure) |
| Pipeline wiring verified | ❌ NO |
| Contract test | ❌ NO |
| Implementation deferred | ✅ YES (cycle 159+) |

## 8. References

- `PRIVACY_BACKENDS_INVESTIGATION_2026-09-24.md` (cycle 158+ broader audit).
- `PRIVACY_REDIS_INVESTIGATION_2026-09-24.md` (Redis audit, prior cycle 158+).
- `PRIVACY_S3_INVESTIGATION_2026-09-24.md` (S3 audit, prior cycle 158+).
- `PRIVACY_QDRANT_INVESTIGATION_2026-09-24.md` (Qdrant audit, prior cycle 158+).
- `src/backend/core/privacy/delete_data_subject/_langmem.py` (per-adapter source).
- `src/backend/core/domain/models/langmem_models.py` (LangMem models with `tenant` field).
- v5 prompt P0 #2 ("Privacy erasure: DeleteDataSubject покрытие; ...").
- v4 §10 P1 ("0 importers + migration window + contract test").
- v4 §5 «presence != wiring».
- v4 §3 evidence-first.
