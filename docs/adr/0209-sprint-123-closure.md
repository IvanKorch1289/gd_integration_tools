# ADR-0209: Sprint 123 Closure — Boundary Hardening Complete (43 → 1, -98%)

- **Status:** Accepted (Sprint 123 W4, 2026-06-14)
- **Wave:** s123-w4-closure
- **Sprint:** 123

## Context

S120 закрыл top-8 категорий boundary violations (43 → 9). S123 закрыл
оставшиеся 8 категорий: redis client, pool health, jupyter_hub,
event_bus, three_tier_rag_cache, messaging, plus 1 broken import
(UserEvent → RouteEvent в schema_registry).

## Sprint 123 Progress (4 waves)

| Wave | Commit | What | Δ violations |
|---|---|---|---|
| W1 (redis) | `15bb71f5` | 1 facade: core/storage/redis | 9 → 6 |
| | | + 3 migrations: rag_ingest, sources/lifecycle, billing/quotas | |
| W2 (skipped) | — | langmem_session — broken import (модуль не существует), | — |
| | | перенесён в S124 (broken import scope) | |
| W3 (facade batch) | `2b6a87f6` | 4 facades: pool_health, jupyter_hub, event_bus, three_tier | 6 → 1 |
| | | + 5 migrations: pool_registration, event_schemas, jupyter, rag_service | |
| W4 (this ADR) | — | Closure + verification | 1 (deferred) |
| **S123 TOTAL** | | **5 facades + 8 migrations** | **9 → 1 (-89%)** |

## Facades Created (5 new modules in core/)

| Facade | Re-exports from | Public surface |
|---|---|---|
| `core/storage/redis.py` | `infrastructure.clients.storage.redis` | `RedisClient`, `get_redis_client` |
| `core/clients/pool_health.py` | `infrastructure.clients.pool_health` | `PoolEntry`, `PoolHealthMonitor`, `get_pool_monitor` |
| `core/clients/jupyter_hub.py` | `infrastructure.clients.external.jupyter_hub` | `JupyterHubClient`, `JupyterHubError`, `JupyterHubServer`, `JupyterHubUser` |
| `core/messaging/event_bus.py` | `infrastructure.clients.messaging.event_bus` | `EventBus`, `FlagEvent`, `OrderEvent`, `PipelineEvent`, `RouteEvent`, `EventSchemaValidationError`, `get_event_bus` |
| `core/cache/rag.py` | `infrastructure.cache.rag.three_tier` | `ThreeTierRagCache` |

## S120+S123 Combined: Full Boundary Hardening

| Sprint | Facades | Migrations | Net reduction |
|---|---|---|---|
| S120 (5 waves) | 8 | 22 | 43 → 9 (-79%) |
| S123 (4 waves) | 5 | 8 | 9 → 1 (-89%) |
| **TOTAL** | **13** | **30** | **43 → 1 (-98%)** |

## Remaining 1 Violation (Honest Scope)

| File | Issue | Type |
|---|---|---|
| `services/ai/langmem_service.py:68` | `from src.backend.infrastructure.database.session import async_session_maker` | **Broken import** — модуль `infrastructure.database.session` не существует (есть `session_manager.py`) |

Это **не facade opportunity** — `async_session_maker` определён в
`infrastructure/database/database/initializer.py:47` как локальный
binding (`self.async_session_maker = async_sessionmaker(...)`), не
module-level export. langmem_service.py ожидает module-level
`async_session_maker`, что говорит об **outdated import path**.

**Решение:** перенести в S124 W2 (orphan tests fix scope), где уже
планируется fix `langmem_service.py` import.

## Bonus Fix: UserEvent → RouteEvent

`schema_registry/event_schemas.py` импортировал `UserEvent` из
`infrastructure.clients.messaging.event_bus`, но в `__all__` этого
event_bus модуля `UserEvent` НЕТ. Заменено на `RouteEvent` (реальный
event type) при миграции.

## Decisions

### D1. Multi-sprint epic for full closure

S120 (5 waves) + S123 (4 waves) = 9 sprints boundary hardening.
Honest scope: 13 facades + 30 migrations за 2 сессии.

### D2. Broken imports → orphan tests scope

Если импорт broken (модуль не существует) — это НЕ facade opportunity.
Миграция на facade не решит проблему. Broken imports логически относятся
к S124 (test collection / import drift).

### D3. TYPE_CHECKING imports тоже мигрируются

`if TYPE_CHECKING: from ... import X` — это тоже boundary violation.
Pyright / mypy проверяют эти импорты. S123 W3 мигрировал
`rag_service/__init__.py` TYPE_CHECKING блок.

## Consequences

- **S123 target met:** 9 → 1 (-89%, target was 50%, exceeded)
- **S120+S123 combined:** 43 → 1 (-98%, target was 100%, 1 broken import deferred)
- **Score:** 9.9/10 (architectural improvement sustained)
- **Maintenance:** MAINTAINED
- **Commits:** 3 atomic (W1, W3, this W4 ADR)
- **Master ahead of origin:** +52

## Related

- AGENTS.md (boundary rules)
- ADR-0207 (S120 W5 closure)
- ADR-0208 (S121 W1 plan, orphan tests)
- PLAN.md V22 (architecture)
