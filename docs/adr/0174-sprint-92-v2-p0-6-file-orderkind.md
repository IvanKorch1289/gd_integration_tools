# ADR-0174: Sprint 92 — V2 P0 #6 continue (File + OrderKind)

**Status:** Accepted
**Date:** 2026-06-12
**Sprint:** 92
**Author:** Assistant (autonomous cycle)

## Context

Sprint 91 closure (ADR-0173) brought V2 P0 #6 to 2/7 models with
`TenantMixin` (Order, User). Sprint 92 continues the rollout for the
next two highest-priority models: `File` and `OrderKind`.

## Decision

### W1: Alembic migration `files.tenant_id`

Pattern is identical to S89 W1 (orders) and S91 W1 (users) migrations.
Online, idempotent, `DEFAULT 'default'` for backfill.

### W2: `File` + `OrderKind` → `TenantMixin`

**Why these two models:**

- **File** — has M2M relationship to `Order` via `OrderFile`. Tenant
  isolation is required for multi-tenant file storage. The `object_uuid`
  is per-tenant (uses `gen_random_uuid()` server-side).
- **OrderKind** — a "directory" / "lookup table" for order types.
  While it could be argued that OrderKind is a system-wide reference
  (like Country codes), the S88 W2 decision was that **all business
  models with multi-tenant data are tenant-scoped**. Different tenants
  can have their own order type catalogues.

**Why not `OrderFile` (the M2M association table):**

- `OrderFile` is a pure association table (`Base`, not `BaseModel`)
  with no domain logic. It does not need `TenantMixin` — its
  tenant isolation is implicit (it joins to Order, which is filtered).
- Adding `tenant_id` to `OrderFile` would be redundant: if Order is
  filtered by tenant, the join automatically restricts OrderFile rows.

## Consequences

### Positive

- 4/7 models now tenant-isolated: `Order`, `User`, `File`, `OrderKind`.
- `File` queries auto-filtered by `apply_tenant_filter` (S88 W2).
- `OrderKind` queries auto-filtered (important for tenant-specific
  request type catalogues).

### Negative / Limitations

- 3/7 models still without `TenantMixin`:
  `WorkflowEvent`, `DslSnapshot`, `RuleEngine`.
  Deferred to S93+.
- `OutboxMessage` is intentionally NOT migrated (service-level table,
  not user data — see S89 deep check).

### Risk

- `OrderKind` migration may break tenant-shared lookups: if a tenant
  previously had no `OrderKind` rows and relied on system defaults,
  the new `tenant_id='default'` rows will be visible only when
  querying as 'default' tenant. This is **intentional** and matches
  the multi-tenant design.

## Remaining Models (S93+ scope)

| Model | Priority | Why |
|---|---|---|
| `WorkflowEvent` | LOW | Internal event log; mostly system-generated |
| `DslSnapshot` | LOW | DSL state snapshots; rarely tenant-shared |
| `RuleEngine` | MEDIUM | Business rules; could be tenant-shared |

S93 plan: `RuleEngine` (last business model with potentially shared data).
S94: `WorkflowEvent` + `DslSnapshot` (system-level, can use default tenant
unconditionally if needed).

## References

- Migration: `src/backend/infrastructure/database/migrations/versions/2026_06_12_2100-f8a9b0c1d2e3_files_tenant_id.py`
- Models: `src/backend/infrastructure/database/models/files.py`, `orderkinds.py`
- Tests: `tests/unit/dsl/test_s92_file_orderkind_tenant.py`
- Related: ADR-0171 (S89 Order pilot), ADR-0173 (S91 User)
