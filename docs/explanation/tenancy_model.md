# Tenancy model

`core.tenancy.TenantContext` — frozen dataclass + ContextVar. Все
нижележащие слои (DB, Redis, logs, metrics) используют контекст для
изоляции.

## Текущее состояние (Sprint 5)

* `TenantContext` доступен;
* admin endpoints `/admin/tenants` и `/admin/tenants/{id}` — stub-режим;
* Streamlit page 70_Tenants рендерит scaffold UI.

## Что в Sprint 7+ (К3 RLS)

* Реальный tenant-registry в БД;
* PostgreSQL RLS policy per-tenant;
* Per-tenant Redis namespace;
* SLO-метрики per-tenant.

## Quotas

`core.tenancy.QuotaTracker` — поверх Redis, fail-open semantic
(если Redis недоступен — quota не блокируется, событие в логи).

См. также:
* [ADR Tenancy](../../docs/adr/ADR-Tenancy.md) (если существует);
* Streamlit page **70_Tenants** — admin UI.
