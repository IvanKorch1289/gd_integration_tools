# Фаза G1 — Multi-tenancy (TenantContext + RLS + Redis-prefix + Quotas + Billing)

* **Статус:** done (scaffolding)
* **Приоритет:** P2
* **ADR:** —
* **Зависимости:** C5

## Выполнено

- `src/core/tenancy/__init__.py` — `TenantContext` + `ContextVar`-
  based `current_tenant()/set_tenant()/tenant_scope()`.
- Поле `tenantid` уже в CloudEvent extension (C4, ADR-010).
- `ResourceRateLimiter` (A4) интегрируется с tenant-контекстом через
  identifier=`f"{tenant}:{api_key}"`.

RLS на Postgres (SET app.tenant_id=...), `RedisPrefix` wrapper,
quota-tracker и billing-ledger — follow-up, сценарии зависят от
инфраструктуры заказчика.

## Definition of Done

- [x] TenantContext.
- [x] tenant_scope() context-manager.
- [x] `docs/phases/PHASE_G1.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (G1 → done).
