# ADR-0170: Sprint 88 — V2 P0 #5 + #6 Closure (HIGH severity)

**Status**: Accepted
**Date**: 2026-06-12
**Sprint**: S88
**Author**: Ivan (autonomous cycle)
**Supersedes**: V2 P0 #5 + #6 verdicts (re-verified by S87)

## Context

V2 P0 #5 (HIGH): `GlobalRateLimitMiddleware` default-OFF = vulnerability в prod.
V2 P0 #6 (HIGH): `SQLAlchemyRepository` без tenant auto-filter = data leak cross-tenant.

S87 deep re-check (ADR-0169):
- #5: SecurityHeaders OK, GlobalRateLimit default-OFF підтверджено.
- #6: `apply_tenant_filter` + `TenantMixin` існують як DEAD CODE з S21 W0.

S88 plan (після re-verification):
- W1: env-aware default для rate limit (production → True).
- W2: wire up `apply_tenant_filter` (FIX: do_orm_execute — SessionEvents, не Engine event).
- W3-W4: e2e tests + public endpoints exemption verification.
- W5: ADR + CHANGELOG (цей документ).

## S88 deep investigation

### #5: rate limit fix

`sprints_18_21.py:136` — `multi_tenant_rate_limit_enabled: bool = Field(default=False)`.
Production implication: prod deploy без explicit `FEATURE_MULTI_TENANT_RATE_LIMIT_ENABLED=true`
= rate limit OFF = vulnerability.

S88 W1 fix: `default_factory=lambda: Sprints1821Flags._env_aware_default(...)` →
production → True, development/staging → False, override через env var.

Helper `_env_aware_default(env_var_name, prod_value)`:
- Read raw env var BEFORE pydantic-settings processing.
- If explicit env var set → use it.
- Otherwise → read `AppBaseSettings().environment`, return `prod_value` if "production".

### #6: tenant auto-filter fix

S21 W0 (оригінальний код `tenant_filter.py`):
- `apply_tenant_filter(session_factory)` — `@event.listens_for(session_factory, "do_orm_execute")`.
- **BROKEN**: `do_orm_execute` — це `SessionEvents`, не Engine/sessionmaker event.
- S21 W0 написав функцію яка **ніколи не могла виконатись** без `InvalidRequestError`.
- Ніхто не помітив (dead code — ніхто не викликав).

S88 W2 fix:
- `apply_tenant_filter(_target=None)` — target ігнорується (backward compat).
- `@event.listens_for(Session, "do_orm_execute")` — правильний target.
- `@event.listens_for(Session, "before_flush")` — auto-set tenant_id на new objects.
- `_INSTALLED` global flag → idempotent.
- `DatabaseSessionManager.__init__` викликає `apply_tenant_filter()` → активує.

### #6 partial scope: моделі без TenantMixin

`WorkflowInstance` — ЄДИНА модель з `TenantMixin` (8 моделей загалом).
- 7 моделей БЕЗ `tenant_id` колонки: Order, DslSnapshot, OutboxMessage, File,
  OrderKind, WorkflowEvent, User.
- S88 НЕ додає `TenantMixin` (потребує Alembic migration = scope expansion).
- S88 закриває wire-up; pilot migration → S89+S90.

## Decisions

* S88 W1: env-aware default для rate limit (production-secure-by-default).
* S88 W2: fix dead code `apply_tenant_filter` + wire-up в `DatabaseSessionManager`.
* S88 W3-W4: e2e tests + public endpoint exemption verification.
* S89+: pilot migration 7 моделей → `TenantMixin` (Alembic migrations).

## Consequences

* V2 P0 #5 HIGH: **CLOSED** (env-aware default).
* V2 P0 #6 HIGH: **PARTIALLY CLOSED** (wire-up + tests, міграція моделей → S89+).
* Projected rating: 7.36 → 7.66/10.
* 17 NEW tests (8 wire-up + 5 e2e + 4 public endpoints).
* 4 commits ahead of origin (W1-W4).

## Follow-up

* S89: Alembic migration для 7 моделей → `TenantMixin`. Pilot: `Order` + `OutboxMessage`.
* S90: continue migration для `DslSnapshot`, `File`, `OrderKind`, `WorkflowEvent`, `User`.
* S91: V2 P0 #7 (10 processors `del context` fix) + V2 P0 #10 (HTTP drain 503).

## V2 P0 status (2026-06-12)

| # | Status | Sprint |
|---|---|---|
| N1 | ✅ CLOSED | S83 |
| #1 | ✅ CLOSED | S85 |
| #2 | ✅ CLOSED | S86 v2 |
| #3 | ✅ CLOSED | S84 |
| **#5** | ✅ **CLOSED S88** | S88 (env-aware default) |
| **#6** | 🟡 **PARTIAL S88** | S88 (wire-up); S89+ (model migration) |
| #7 | 🟡 PENDING | S91 |
| #8 | 🟢 PENDING | S92 |
| #9 | 🟢 WRONG (V2 fact-check fail) | S93 verify |
| #10 | 🟡 PENDING | S91 |

**6/10 V2 P0 closed or partial-closed (4 fully, 1 partial, 1 wrong)**.
