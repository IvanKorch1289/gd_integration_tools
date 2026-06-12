# ADR-0171: Sprint 89 — V2 P0 #6 Pilot Migration (Order → TenantMixin)

**Status**: Accepted
**Date**: 2026-06-12
**Sprint**: S89
**Author**: Ivan (autonomous cycle)
**Supersedes**: S22 carryover `[wave:s22/k1-w0-add-tenant-id-columns]` (не виконано)

## Context

S87 deep re-check (ADR-0169): V2 P0 #6 РЕАЛЬНИЙ — `apply_tenant_filter` існує, але
`Order`, `OutboxMessage`, `File`, `OrderKind`, `WorkflowEvent`, `User`, `DslSnapshot`
НЕ мають `tenant_id` колонки → auto-filter no-op.

S88 (ADR-0170): wire-up `apply_tenant_filter` (S88 W2) + e2e tests (S88 W3-W4).
Залишилось: пілотна schema migration для реальних моделей.

S22 carryover: `[wave:s22/k1-w0-add-tenant-id-columns]` для `orders`/`users`/`files`
— НЕ зроблено. S89 закриває pilot для `orders`; `users`/`files` — S90+.

## S89 deep investigation

* `Order` (table `orders`) — створена 2025-03-10 (initial migration `20036813ff7c`),
  active production use case з API endpoints (`orders.py:43`, `skb.py:59`).
* `OutboxMessage` (table `outbox_messages`) — створена 2026-04-20, **service-level**
  таблиця (transactional outbox pattern). **НЕ потребує** tenant isolation.
* `RuleEngineRuleset` — має `tenant_id` (nullable, S21 W0) + RLS policy — V2 #6
  частково covered (Postgres-level isolation).
* `WorkflowInstance` — має `TenantMixin` (S21 W0) + RLS policy — V2 #6 covered.

## S89 plan execution

### W1: Alembic migration `d6e7f8a9b0c1_orders_tenant_id`

* `ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'`
* `CREATE INDEX ix_orders_tenant_id`
* `UPDATE orders SET tenant_id='default' WHERE IS NULL` (idempotent backfill)
* Online migration в Postgres 11+ (metadata-only)
* Idempotent guard через `inspector.get_columns('orders')`
* Downgrade: `DROP INDEX` + `DROP COLUMN IF EXISTS`

### W2: Order model — `tenant_id` Mapped[str]

* `Mapped[str] = mapped_column(String(64), nullable=False, default='default', index=True)`
* Type fix: `errors Mapped[str]` → `Mapped[str | None]` (original was wrong)

### W3: Order(BaseModel, TenantMixin)

* Видалив окремий `tenant_id` column (TenantMixin надає)
* `Order.__mro__` includes `TenantMixin`
* `_is_tenant_aware(Order) = True` — auto-filter активний
* Вибрав TenantMixin, а не власний column — DRY, single source of truth

### W4: 8 regression tests

* Order.__mro__ includes TenantMixin
* Order.tenant_id column spec
* _is_tenant_aware(Order) = True
* Order imports не ламаються
* Order relationships (order_kind, files) збережені
* 10 існуючих полів + tenant_id — всі present

### W5: цей ADR

## Decisions

* S89 scope: **Order пілот** + Order ТІЛЬКИ (не всі 7 моделей).
* `OutboxMessage` виключено з S89 (service-level таблиця, не user data).
* Online migration pattern (NOT NULL DEFAULT) — backward compat з existing rows.
* TenantMixin (а не власний column) — DRY з WorkflowInstance pattern.

## Consequences

* V2 P0 #6 HIGH: **pilot CLOSED для Order** (1/7 моделей tenant-isolated).
* S88+S89: `apply_tenant_filter` active + Order має tenant_id → auto-filter works.
* S90: міграція `User` + `File` + `OrderKind` (3 наступні).
* S91+: `DslSnapshot`, `WorkflowEvent`, `OutboxMessage` (опціонально).
* 8 NEW tests, 4 commits, 1 ADR.

## V2 P0 status (2026-06-12, after S89)

| # | Status | Sprint |
|---|---|---|
| N1 | ✅ CLOSED | S83 |
| #1 | ✅ CLOSED | S85 |
| #2 | ✅ CLOSED | S86 v2 |
| #3 | ✅ CLOSED | S84 |
| #5 | ✅ CLOSED | S88 |
| **#6** | 🟡 **PILOT CLOSED** | S88 (wire-up) + S89 (Order pilot) |
| #7 | 🟡 PENDING | S91 (10 processors) |
| #8 | 🟢 PENDING | S92 (audit distinction) |
| #9 | 🟢 WRONG | S93 verify not needed |
| #10 | 🟡 PENDING | S91 (HTTP drain 503) |

**5/10 fully closed, 1/10 partial-pilot-closed, 3/10 pending, 1/10 V2 fact-check wrong**.

## Follow-up

* S90: Alembic migrations для `User` + `File` + `OrderKind` (TenantMixin apply).
* S91: V2 P0 #7 (10 processors `del context` fix) + V2 P0 #10 (HTTP drain 503).
* S92: V2 P0 #8 (audit log public vs failed-auth distinction).
* Long-term: 6/10 моделей tenant-isolated (`Order` S89, `WorkflowInstance` S21,
  `RuleEngineRuleset` S21). 4/10 залишаються (DslSnapshot, File, OrderKind, User,
  WorkflowEvent) — S90-S95 sprint backlog.
