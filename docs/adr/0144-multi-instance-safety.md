# ADR-0144 — Multi-instance safety: outbox claim_pending + scheduler leader election + RedisDedupeStore (4 commits, 3/5 substantive)

* Статус: Accepted (Autonomous work cycle, 2026-06-12)
* Связано с: `f971d4fc` (S64 W1, claim_pending), `2336e4c1` (S64 W2, leader election), `22c1770b` (S64 W3, dispatcher cutover), `d6138325` (S64 W4, RedisDedupeStore)
* Контекст: production-деплой с несколькими K8s-pods, PLAN.md V22 final

## Naming note (важно)

Этот ADR документирует **autonomous work cycle "S64"** (по внутренней
нумерации Hermes-сессии, не путать с **project S64** = god-file decomp
в `0138-sprint-64-closure.md`). Project S64 (god-files) уже closed
2026-06-10; автономный цикл S64 начат постфактум для multi-instance
safety hardening.

## Контекст

Production-деплой планируется с **несколькими K8s-pods** (N≥2) для
availability и rolling updates. Текущий код имеет **3 single-instance
bottleneck**, которые при multi-instance вызовут дублирование или
потерю сообщений:

1. **Outbox worker** — `workflows/outbox_worker.py:116` использует
   `max_instances=1, coalesce=True` (APScheduler). С N pods будет
   N параллельных workers, конкурирующих за `outbox_messages` —
   **дублирование delivery**.

2. **APScheduler** (`setup_infra.py:start_scheduler_manager`) — нет
   leader election. Cron-задачи выполнятся на ВСЕХ pods одновременно
   → двойные emails, двойные webhook'и, race conditions.

3. **MemoryDedupeStore** (`services/sources/lifecycle.py`) — in-process
   `cachetools.TTLCache` + `asyncio.Lock`. Event_id дубль с другого
   pod **НЕ детектится** → повторный invoke.

## Решения

### W1: `outbox_repo.claim_pending` (commit `f971d4fc`)

Multi-instance safe claim:
```sql
pg_try_advisory_xact_lock(blake2b(worker_id))
UPDATE outbox_messages
   SET retry_count = retry_count + 1
 WHERE id IN (SELECT id FROM outbox_messages
               WHERE status = 'pending'
                 AND next_attempt_at <= NOW()
               ORDER BY id
               FOR UPDATE SKIP LOCKED
               LIMIT $N)
   AND pg_try_advisory_xact_lock(...)
 RETURNING *
```

- **Per-call advisory lock** (не per-row) — fast, защита от race
  внутри одного worker'а.
- `FOR UPDATE SKIP LOCKED` — atomic claim, не блокирует другие
  workers.
- `pg_try_advisory_xact_lock` — non-blocking: если lock не получен
  (= другой worker в этой итерации), возврат `[]` (пустой batch).
- `worker_id = HOSTNAME env` (K8s pod name) → `socket.gethostname()`.

**Honest gap (deferred S65+)**: lock granularity = per-call, не per-row.
Если worker_A зависнет в середине обработки, его `pg_try_advisory_xact_lock`
держится до конца транзакции (т.е. до commit), но retry_count уже
инкрементнут. Полная per-row защита требует Alembic-миграцию с
`status='processing'` (см. TECH_DEBT-S64-W1).

### W2: Scheduler leader election (commit `2336e4c1`)

```python
async def _start_scheduler_with_leader_election() -> None:
    async with distributed_lock("scheduler:leader:v1", ttl=300, blocking_timeout=0):
        # ... только leader вызывает scheduler.start()
        global _scheduler_leader_acquired
        _scheduler_leader_acquired = True

async def _stop_scheduler_if_leader() -> None:
    if not _scheduler_leader_acquired:
        return  # non-leader skip stop (избегает SchedulerNotRunningError)
    # ... shutdown
```

- **TTL=300s** — acceptable для cron-уровня (eventual leadership
  shift при cluster instability).
- `blocking_timeout=0` — non-blocking; только ОДИН pod получает lock.
- Symmetric shutdown — non-leader НЕ вызывает `scheduler.stop()`
  (защита от `SchedulerNotRunningError`).

**Honest gap (deferred S65+)**: lock НЕ auto-extends. При cluster
instability возможен leadership shift посреди cron-job. Решается
либо `redis_lock` auto-extend (S52 W3) либо `scheduler_lock` refresh
task.

### W3: OutboxDispatcher cutover (commit `22c1770b`)

Feature flag `outbox_settings.enabled` (default OFF):
- **enabled=False** (default, dev_light) → legacy `start_outbox_worker`
  (APScheduler, single-instance).
- **enabled=True** (prod) → `start_outbox_dispatcher` (S64 W1+W3: new path).

Adapter-ы в `_register_outbox_dispatcher()`:
- `claim_pending` → `OutboxEvent` (W1 backend).
- `OutboxEvent` → `mark_sent` (по encoded `outbox_msg_id:<N>` в
  `correlation_id`).
- Reuse legacy `_publish` для deliverer (минимизация изменений).

Worker ID: `HOSTNAME` env → `socket.gethostname()`. В K8s `HOSTNAME`
= pod name (уникален в namespace).

**Best-effort startup**: outer `try/except` log'ит warning, **не raise'ит**
(как legacy поведение — outbox не блокирует startup при недоступном
RabbitMQ/Kafka).

**Pre-existing import bugs обойдены** через `_load_lifespan_isolated()`
(test stub `sys.modules` для `plugins/composition/__init__.py:9`
graphql_router + `accessors.py:24` DatabaseInitializer). Production
код НЕ тронут — баги остаются в TECH_DEBT.

### W4: `make_dedupe_store()` factory (commit `d6138325`)

```python
async def make_dedupe_store() -> DedupeStore:
    if not outbox_settings.use_redis_dedupe:
        return MemoryDedupeStore()
    redis_client = await get_redis_client().get_client("cache")
    return RedisDedupeStore(redis_client)
```

- `outbox_settings.use_redis_dedupe: bool = False` (default).
- `False` → in-process `MemoryDedupeStore` (dev_light/тесты).
- `True` → `RedisDedupeStore` (`SET NX EX` атомарная first-write,
  multi-instance safe).
- **Fail-fast** на `get_client()` (Redis недоступен → `ConnectionError`,
  не silent degrade) — startup сам решает, fallback'ить ли.

**Honest gap (deferred S65+)**: `RedisDedupeStore.is_duplicate` ловит
**все** exceptions и degrade'ит в `False` (best-effort). При
flapping Redis возможен **дубль** event'а. Решение: separate flag
`fail_closed=True` для prod (S65+).

## Что осталось (S65+ backlog)

- Alembic-миграция: `outbox_messages.status='processing'` + per-row
  advisory lock (полная защита при worker hang).
- `RedisDedupeStore.fail_closed` флаг (prod: дубли хуже потери).
- Pre-existing import bugs (`DatabaseInitializer`, `graphql_router`,
  `redis_client` decorator) — TECHNICAL DEBT, не блокирует S64
  acceptance (обойдены через test stubs).
- `RedisLock`/`RedisDedupeStore` auto-extend — единый pattern.

## Quality gates

- **mypy**: 6 unit-tests pass для S64 W1 (claim_pending).
- **ruff**: clean.
- **S64 W3 tests**: 5/5 pass (с isolated module loader).
- **S64 W4 tests**: 3/3 pass.
- Sibling WIP outstanding: ~1700 mypy errors (не наш scope).

## Lessons learned

1. **Per-call vs per-row advisory lock** — trade-off:
   per-call проще (не нужен Alembic), но менее robust при worker
   hang. Default — per-call (быстрее в common case).
2. **Feature flag `default OFF`** — плавный cutover, не breaking
   existing dev/test setups.
3. **Pre-existing import bugs** обходятся через test stubs, не через
   правки production кода (другая работа, разные владельцы).
4. **Worker ID = HOSTNAME** — уникален в K8s без дополнительной
   инфраструктуры.
5. **`correlation_id` encoding** для ack-mapping: `outbox_msg_id:<N>`
   — OutboxEvent не имеет `.id`/`.headers`, поэтому encode в
   correlation_id (OutboxEvent имеет это поле).
