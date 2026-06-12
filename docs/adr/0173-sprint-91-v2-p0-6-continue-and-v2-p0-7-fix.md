# ADR-0173: Sprint 91 — V2 P0 #6 continue (User) + V2 P0 #7 fix (processors)

**Status:** Accepted
**Date:** 2026-06-12
**Sprint:** 91
**Author:** Assistant (autonomous cycle)

## Context

Sprint 90 closure (ADR-0172) identified two high-value follow-ups:

1. **V2 P0 #6** (HIGH) — only 1/7 models has `TenantMixin` (Order from S89).
   The User model is highest priority next because it gates auth/RBAC
   and is read by every request.
2. **V2 P0 #7** (MEDIUM) — 10 processors in `dsl/engine/processors/` had
   `del context` at the start of `_run()`. This is **active deletion** of
   the local `context` parameter, blocking any future use (e.g.
   tenant_id, correlation_id propagation to processors).

## Decision

### W1: Alembic migration `users.tenant_id`

**Pattern: copy of S89 W1 orders migration verbatim, with table name
swapped.** Online migration (Postgres 11+), `DEFAULT 'default'` for
backfill, idempotent guard via `inspector.get_columns()`.

```sql
ALTER TABLE users ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT 'default';
CREATE INDEX ix_users_tenant_id ON users (tenant_id);
UPDATE users SET tenant_id = 'default' WHERE tenant_id IS NULL;
```

### W2: `User(BaseModel, TenantMixin)`

Apply `TenantMixin` to User model. TenantMixin provides `tenant_id`
column — no separate `mapped_column` needed (unlike Order S89 W2
which initially had a redundant `tenant_id` mapped_column before
W3 fix).

`apply_tenant_filter` (S88 W2) now auto-filters User queries when
`current_tenant()` is not None.

### W3: 10 processors `del context` → `_ = context`

V2 audit (S87 re-verification) was **partially wrong**:
- V2 claimed `skill_invoke.py` had `del context` — **WRONG**
  (`skill_invoke` doesn't exist; V2 confused it with a different file).
- V2 claimed "10 processors" — **CORRECT** (verified S91 W3: 10
  files in `agent_dsl/*` + `ml_predict.py`).

Fix: replace `del context` with `_ = context  # Зарезервировано`:

```python
# Before:
async def _run(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
    del context
    ...

# After:
async def _run(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
    _ = context  # Зарезервировано для майбутнього use (correlation, tenant_id)
    ...
```

**Why `_ = context` and not just remove the line:**
- `_ = x` is an explicit "I know I don't use this" — passes linters
  (no "defined but never used" warning).
- Preserves the value for future use (e.g. when tenant_id/correlation
  propagation is added to processors).
- No risk of `UnboundLocalError` if someone later references `context`.

**Why not change the signature to `_run(self, exchange)` (remove `context`):**
- Abstract base class / protocol might enforce the signature.
- `context` is a standard part of the processor interface (see
  `ExecutionContext` imports in all 10 files).
- Removing the param would require changes at every callsite.

## Consequences

### Positive

- 2/7 models now tenant-isolated: `Order`, `User`. Both critical
  (User = auth/RBAC, Order = business data).
- All 10 processors can now safely use `context` (tenant_id,
  correlation_id, trace propagation) without `UnboundLocalError`.
- No new abstractions: codemod-style replacement (sed for 9 files,
  manual for 1 file with inline comment).
- 6 NEW regression tests verify both changes.

### Negative / Limitations

- 5/7 models still without `TenantMixin`:
  `File`, `OrderKind`, `WorkflowEvent`, `DslSnapshot`, `RuleEngine`.
  Deferred to S92+.
- 9 `ml_predict` is the only processor with `process()` instead of
  `_run()` — separate pattern. Confirmed correct via AST scan in tests.

### Risk

- `_ = context` keeps the reference alive. For a transient `context`
  object this is negligible (CPython refcount drops on next line).
- The TenantMixin on User is **additive** — no existing data is
  modified (only `tenant_id='default'` backfill, which is a no-op
  semantically for the default tenant).

## Alternatives Considered

### A) Remove `context` parameter entirely from 10 processors

**Rejected**: Would require:
- Renaming `_run` to remove the param in each processor
- Updating abstract base / protocol signatures
- Updating 10 callsites
- High churn for 0 user-visible benefit

### B) Apply `TenantMixin` to all 5 remaining models in S91

**Rejected**: Each model needs:
- Separate Alembic migration (or 1 batch migration)
- Backfill strategy verification
- `__table_args__` and column type audit
- API endpoint impact analysis

5 models × 1 commit = 5+ commits. Out of S91 scope. Tracked in
S92+ as continuation.

## References

- Migration: `src/backend/infrastructure/database/migrations/versions/2026_06_12_2000-e7f8a9b0c1d2_users_tenant_id.py`
- Model: `src/backend/infrastructure/database/models/users.py`
- 10 processors: `src/backend/dsl/engine/processors/agent_dsl/*.py` + `ml_predict.py`
- Tests: `tests/unit/dsl/test_s91_user_tenant_and_processors.py`
- Related: ADR-0170 (S88 W2 apply_tenant_filter wire-up), ADR-0171 (S89 Order pilot), ADR-0172 (S90 pool completion)
