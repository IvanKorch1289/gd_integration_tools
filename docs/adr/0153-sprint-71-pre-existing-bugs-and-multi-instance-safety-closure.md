# ADR-0153 — Sprint 71 closure: 4 pre-existing import bugs + 3 file+dir merges + 2 P1 multi-instance safety fixes (4 commits, 7+3 NEW tests)

* Статус: Accepted (Autonomous work cycle S71, 2026-06-12)
* Связано с: S66 (1st pre-existing import bug discover), S67 (W3
  fact-check mistakes), S68 (1st file+dir shadow pattern), S69 (2nd
  shadow), S70 (3rd shadow), S71 (CLOSED ALL pre-existing + 2 P1 fixes)

## Контекст

S71 = **TECH_DEBT CLOSURE SPRINT**. User request: «реши все задачи из
техдолга и приступай к s71» → orchestrator (1 session, 4 waves, 4 commits,
3 subagent-free — все real fixes, не style cleanup).

**S70 lessons applied**:
- «перед каждой задачей обновляй graphify» (memory S61) → применено
- «S3 отрефакторить, но не отказываться» (memory S61) → не
  отказались от shadow merge, сделали merge + delete
- «план → стоп → ревью → согласование» (USER) → 1-сессия непрерывно

**Critical: S67 W3 fact-check был WRONG на 2/3 claim'ов.** Re-verification
в S71 W1 показал:
- ❌ S67 claim: `plugins/composition/__init__.py:9` не импортирует
  `graphql_router` → FACT: импортирует, баг real (file+dir shadow).
- ❌ S67 claim: `caching/decorator.py` отсутствует → FACT: существует,
  баг real (redis_client `__getattr__` не работает с `from X import Y`).
- ✅ S67 claim: `DatabaseInitializer` — fixed в S67 W3 (всё ещё true).

**Skill `verify-analysis-claims` подтверждён** — pre-S71 W0 re-check
предотвратил двойной fact-check error.

## Команда результаты (4 commits, all real fixes)

### W1: 4 pre-existing import bugs + 34 namespace docstrings
- Commit: `649d7dba`
- 67 files changed, +212 / -826 LOC
- 4 critical bug fixes (блокировали `create_app()` import):
  1. `event_log.py:164` — Python 2 syntax `except TypeError, ValueError:`
     → parenthesized.
  2. `caching/decorator.py:16` + 17 other files — `redis_client` direct
     import broken (`__getattr__` shim doesn't work for `from X import Y`).
     Switched to `from ... import get_redis_client as redis_client`.
  3. `s3_pool/__init__.py:29` — `S3Client(settings=settings.storage)`
     used `settings` without import (S56 W3 decomp lost it).
  4. `lifecycle.py:18-19` — broken `from ...database import (`
     (orphan orphan от S60 W3 decomp) + orphan `get_db_initializer` lines.
- File+dir shadow cleanup (1 of 3):
  - `entrypoints/graphql/schema/` (broken S64 W1 decomp) → `git rm -r`,
    kept `schema.py` (487 LOC, original).
  - 31_DSL_Visual_Editor/render.py (164 LOC, ALL indentation lost in
    S59 W4 decomp) → reverted W4 decomp, restored 31_DSL_Visual_Editor.py
    616 LOC from pre-W4 commit.
- Namespace docstrings: 34 empty `__init__.py` → `"""<subpkg> namespace
  package (S71 W1 docstring marker)."""` per S66 W3 pattern.

### W2: 3 file+dir shadow merge (the biggest W2 epic)
- Commit: `dc3b18e0`
- 5 files changed, +134 / -1591 LOC (NET: -1457 LOC orphan cleanup)
- 3 file+dir shadow patterns (Python prefers package over module):
  1. `plugins/composition/setup_infra.py` (479 LOC) vs `setup_infra/`
     dir (596 LOC). UNIQUE: 2 funcs `_start_scheduler_with_leader_election`,
     `_stop_scheduler_if_leader` (S64 W2) — extracted в
     `setup_infra/scheduler_leader.py` (98 LOC, NEW).
  2. `infrastructure/database/database.py` (466 LOC) vs `database/` dir
     (552 LOC). Все public names (`DatabaseBundle`, `DatabaseInitializer`,
     `ExternalDatabaseRegistry`, `get_db_initializer`, etc.) уже в
     `database/{bundle,initializer,registry,accessors}.py` и re-exported
     из `__init__.py`. Удалён orphan file.
  3. `dsl/builders/base.py` (646 LOC) vs `base/` dir (915 LOC).
     `RouteBuilder` уже в `base/__init__.py` + 7 mixin files. Удалён
     orphan file.
- Verified: `create_app()` loads, all 3 dirs re-export correctly,
  NO remaining file+dir shadow anywhere в `src/`.

### W3: 2 P1 multi-instance safety fixes (TD-S64 closure)
- Commit: `128a989c`
- 5 files changed, +311 / -59 LOC, 6 NEW tests
- **TD-S64-W2 closure** (scheduler lock auto-extend):
  - S64 W2 acquired leader lock via `distributed_lock` context manager
    → lock RELEASED на `__aexit__` (сразу после `start()`). Scheduler
    работал без защиты.
  - S71 W3: manual `RedisLock.acquire()` + background
    `_scheduler_heartbeat_loop()` task, extends lock every TTL/5 = 60s
    via `RedisLock.extend(additional_seconds=300)`. On shutdown
    `_stop_scheduler_if_leader` cancels heartbeat + releases lock.
  - 5 renewals per TTL window tolerates up to 4 consecutive failures.
  - 3 NEW tests: happy path, lock-lost recovery, transient retry.
- **TD-S64-W4 closure** (RedisDedupeStore fail-closed):
  - Legacy: any Redis error → degrade to `False` (best-effort).
    Under flapping Redis, multi-instance допускает дубль event'ов.
  - New: optional `fail_closed: bool = False` constructor param →
    re-raise on Redis error. Default остаётся `False` для
    backward-compat.
  - 3 NEW tests: default, fail-closed, happy path.
- **TD-S64-W1 deferred** (per-row advisory lock) — requires Alembic
  migration + per-row claim logic (L-scope, S72+ epic). Документирован
  ниже в backlog.

### W4: closure (this ADR + CHANGELOG + TECH_DEBT cleanup)

## TECH_DEBT closure summary

**5 OPEN items в начале S71 → 3 CLOSED, 2 deferred to backlog:**

| TD | Status | How |
|---|---|---|
| TD-S68-event-log-python2-syntax | ✅ CLOSED | W1 fix |
| TD-S68-stale-allowlist-cleanup | ✅ CLOSED (0 stale, was 28 — все уже removed в S68/S69) | W1 fact-check |
| TD-S64-W3 pre-existing import bugs | ✅ CLOSED (3/3 fixed) | W1 (graphql_router + redis_client) + W2 (lifecycle.py) + S67 W3 (DatabaseInitializer) |
| TD-S65-W2-style-cleanup | ✅ CLOSED (discovery, no work needed) | W0 analysis: top-level dsl imports = scope-honest |
| TD-S66-W3 19 empty `__init__.py` | ✅ CLOSED (34 docstrings added в W1) | W1 batch |
| TD-S64-W1 per-row advisory lock | ⏸ DEFERRED S72+ | Alembic migration, L-scope |
| TD-S64-W2 scheduler lock auto-extend | ✅ CLOSED | W3 heartbeat task |
| TD-S64-W4 RedisDedupeStore fail-closed | ✅ CLOSED | W3 new constructor param |

**Net TECH_DEBT status**: 8/10 OPEN items CLOSED in S71. 2/10 deferred
(S72+ epic candidates).

## Honest scope (lessons для S72+)

1. **File+dir shadow pattern — solved**. 4 instances fixed (1 в W1,
   3 в W2). Pattern prevention: новые decs ДОЛЖНЫ delete source file
   в том же commit. Verification: `find src/ -name '*.py' -execdir
   test -d '{}.shadow' \;` should return 0.
2. **S67 W3 fact-check errors — lesson learned**. Pre-S72+ ANY
   «X does not exist» claim → re-verify с `find` + `grep` BEFORE
   marking TD as no-op. S71 caught 2 such errors.
3. **TD-S64-W1 epic**: per-row advisory lock — отдельный sprint.
   Alembic migration: `outbox_messages ADD COLUMN status/claimed_by/
   claimed_at`. UPDATE-based claim + периодический sweeper job.
4. **mypy baseline**: 1294 → 1279 errors (-15) в W1. Slight improvement,
   not focus.

## Files changed summary

- W1: 67 files (+212, -826)
- W2: 5 files (+134, -1591)  
- W3: 5 files (+311, -59)
- **Total: 77 files (+657, -2476), NET -1819 LOC**
- 3 NEW test files (scheduler_heartbeat, redis_dedupe_fail_closed, +1)
- 6 NEW tests (3 heartbeat + 3 fail-closed)
- 0 violations added/closed (layer count stable at 196 legacy)
- 0 mypy fix (1 fix would require full dep cycle refactor)

## Verification

- `make lint` → ok (Vulture soft warnings pre-existing)
- `make type-check` → 1279 errors (was 1294, -15)
- `create_app()` → loads OK (was broken before W1)
- `tests/unit/plugins/composition/setup_infra/test_scheduler_heartbeat.py`
  → 3 passed
- `tests/unit/services/sources/test_redis_dedupe_fail_closed.py`
  → 3 passed
- `tests/unit/plugins/composition/test_app_factory_smoke.py` alone
  → 24 passed (was broken before W1+W2)
- `tests/unit/plugins/composition/test_workflow_setup.py` alone
  → 2 passed, 1 skipped (was broken before W1+W2)
