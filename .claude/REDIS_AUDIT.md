# REDIS_AUDIT.md — Wave 1.4 baseline

Аудит использования Redis по проекту и решение, что остаётся в Redis,
а что мигрирует в постоянные хранилища (PostgreSQL / MongoDB / ClickHouse).

## Принцип

* **Redis** — горячие данные с TTL, атомарные счётчики, pub/sub, очереди-streams,
  локи. Утрата при flush / OOM-evict допустима.
* **PostgreSQL** — версионируемые сущности, требующие истории и аудита.
* **MongoDB** — chat history, agent memory, workflow state (nested, flexible).
* **ClickHouse** — append-only audit log, телеметрия (long-term).
* **Vault / PostgreSQL** — секреты и сертификаты (см. Wave 2.1).

## Остаётся в Redis (горячие данные)

| Префикс ключа | DB | Назначение | TTL |
|---------------|----|------------|-----|
| `cache:*` | 0 | L2 кэш API-ответов / response_cache (`CachingDecorator`) | 60–1800s |
| `s3:metadata:*` | 0 | S3 metadata cache (`metadata_cache`) | 300s |
| `s3:exists:*` | 0 | S3 existence cache (`existence_cache`) | 60s |
| `ai-cache:*` | 0 | AI semantic cache (векторы) | по конфигу |
| `ratelimit:*` | 2 | rate limits (`fastapi-limiter`, ResourceRateLimiter) | sliding window |
| `quota:*` | 2 | API quotas | по тарифу |
| `lock:*` | 0 | distributed locks (`RedisLock` / `redis.asyncio.Lock`) | 60s default |
| `idempotent:*` | 1 | dedup в очереди | 24h |
| `inbox:*` | 1 | inbox dedup | 7d |
| `webhook:subs` | 1 | подписки webhook (pub/sub) | persistent (registry) |
| `webhook:dlq` | 1 | DLQ failed webhooks | до ручного разбора |
| `ws:groups:*` | 1 | WebSocket групп-членство (pub/sub) | по сессии |
| `apikey:*` | 0 | API ключи hot-cache (TTL = grace period) | 5–60min |
| `cert:fp:*` | 0 | fingerprint сертификатов (НЕ PEM) | 5min |
| `bulkhead:*` | 0 | bulkhead-метрики (`infrastructure/resilience/bulkhead`) | сессионные |

## Мигрируется из Redis

| Источник (старое) | Назначение | Что мигрирует | Причина |
|-------------------|------------|---------------|---------|
| `dsl_snapshot:*` | **PostgreSQL** таблица `dsl_snapshots` (Wave 1.4) | определения маршрутов, версионирование | требуется история, A/B, rollback; НЕ горячие данные |
| `apikey_audit:*` | **ClickHouse** таблица `audit_log` (Wave 5.1) | audit-trail обращений к API ключам | append-only, аналитика, долгосрочное хранение |
| `agent:memory:*` (LRANGE/HGETALL) | **MongoDB** `agent_memory_*` (Wave 0.10) | conversation / scratchpad / facts | долгосрочная память агентов с TTL и поиском |

## Архитектурные правила

* Сертификаты (PEM-тело) **никогда** не лежат в Redis — только в Vault/PostgreSQL.
  В Redis допускается только short-TTL **fingerprint** для проверки кэша.
* Snapshot маршрутов и audit log не используют Redis — данные постоянные.
* Для всех новых горячих данных требуется явный TTL и оценка cost recovery
  при потере Redis.

## Связанные шаги PLAN.md v5

* Wave 0.10 — AgentMemory мигрирован (см. `services/ai/agent_memory.py`).
* Wave 1.4 — `dsl_snapshot:*` мигрирует в PostgreSQL (alembic миграция
  `dsl_snapshots`); `versioning.py` переключается на SQLAlchemy.
* Wave 2.1 — CertStore (Vault/PostgreSQL).
* Wave 5.1 — Audit log (ClickHouse, выполнено).
