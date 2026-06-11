# ADR-0140 — Sprint 66 closure: 3 god-file decomp (event_store, setup, lifecycle) + 1 sibling WIP fixup (4+1 commits, 5/5 substantive)

* Статус: Accepted (Sprint 66 W5, 2026-06-10)
* Связано с: b894e8e9 (W1), 33c4800c (W2), 01dae8a7 (W3), 61db4cf1 (W4 fixup), this ADR (W5)
* Контекст: PLAN.md V22 final, S49-S65 pattern continuation

## Контекст

Sprint 66 закрыл 3 god-file + 1 sibling WIP:
- event_store.py 468 LOC (9 classes + 3 funcs) — per-concern file split
- setup.py 854 LOC (26 funcs) — per-concern file split
- lifecycle/__init__.py 585 LOC (lifespan 538 LOC extraction) — completes S82 sibling decomp (ADR-0105)
- authorization_gateway.py 530 LOC (sibling WIP dead code) — deleted

## Решения

1. **Per-concern file split (event_store.py, S66 W1)** — 9 classes + 3 funcs → 5 files:
   - types.py: EventStream, Event (2 data types)
   - store.py: EventStore (ABC) + InMemoryEventStore (impl)
   - cqrs.py: Projection, CommandBus, QueryBus, CQRSMixin (4 CQRS classes)
   - processor.py: EventStoreProcessor (DSL integration)
   - helpers.py: 3 module-level funcs (get/set/reset)

   Cross-imports added: `cqrs.py` and `processor.py` import `EventStream` + `Event` from `types.py`. **Lesson**: when extracting classes into multiple files, files downstream in the dependency chain need explicit cross-imports.

2. **Per-concern file split (setup.py, S66 W2)** — 26 funcs → 5 files:
   - helpers.py: _register_crud_actions (shared helper, 1 func)
   - registers_domains.py: 7 domain funcs
   - registers_integrations.py: 8 integration funcs
   - registers_workflow.py: 9 workflow funcs
   - orchestrator.py: register_action_handlers (main entry, 1 func)

3. **Single function extraction (lifecycle/__init__.py, S66 W3)** — sibling S82 (ADR-0105) W1-W4 extracted protocols/bootstrap/v11/watchers but left `async def lifespan()` (538 LOC) in __init__.py. S66 W3 extracts it to `lifespan.py`. **Result**: __init__.py 585 → 25 LOC of pure re-exports.

4. **Sibling WIP fixup (authorization_gateway.py, S66 W4)** — S60 W4 decomp created a package but didn't delete the original .py. Python prefers package over .py, so it was dead code (530 LOC). S66 W4 deletes it.

## Изменения

| File | Before | After | Decomposition |
|------|--------|-------|----------------|
| event_store.py | 468 | 0 (deleted) | 9 classes + 3 funcs → 5 files (per-concern) |
| setup.py | 854 | 0 (deleted) | 26 funcs → 5 files (per-concern) |
| lifecycle/__init__.py | 585 | 25 | lifespan() → lifespan.py (538 LOC) |
| authorization_gateway.py (sibling WIP) | 530 | 0 (deleted) | dead code, S60 W4 already created package |
| **Total** | **2437** | **0 (replaced)** | **18 files created** |

## Quality gates (S66 scope)

- **mypy**: S66 changes clean (sibling WIP graphql_router/invoker_pb2 are pre-existing, not my code)
- **ruff**: clean for S66 changes
- Sibling WIP outstanding: 1800+ mypy errors (unchanged)

## Patterns re-used from S49-S65

- **MRO composition** (S49-S65 all MRO waves)
- **Per-concern file split** (S57 W4 sink_publish, S58 W3 format_converters, S59 W1 banking_processors, S60 W2 cdc, S62 W2 vocabulary, S63 W1 loading, S64 W2 repositories, S64 W3 database, S65 W1 components, S65 W2 rpa, S65 W3 grpc, S66 W1 event_store, S66 W2 setup)
- **Single function extraction** (S66 W3 lifespan — new pattern: when only 1 top-level func remains, extract it for clarity)
- **Sibling WIP cleanup** (S66 W4 authorization_gateway.py deletion — sibling S60 W4 created package but didn't delete original)

## Lessons learned (для sprint-execution skill)

1. **Cross-imports needed for type-dependent classes** (S66 W1 NEW): when classes reference other classes from different files in the same package, the downstream files need explicit cross-imports. S65 mixin files didn't need them, but event_store `cqrs.py` (uses `EventStream`) and `processor.py` (uses `EventStream`) did.

2. **S66 W3 pattern: extract single function from `__init__.py`** — when the package is otherwise complete and only one big function remains, extracting it shrinks `__init__.py` to a thin re-export layer. The original `lifecycle/__init__.py` was 585 LOC with `lifespan` taking 538; after, `__init__.py` is 25 LOC.

3. **Sibling WIP detection: check `git log --oneline -- <file>` for original .py after package creation** (S66 W4) — if a package exists but the original .py file is also on disk, it's dead code. Python prefers package over .py, so it's silently shadowed but bloats the repo.

## Files Modified

### Created (12 new files)
- `src/backend/dsl/processors/event_store/{__init__,types,store,cqrs,processor,helpers}.py` (6 files)
- `src/backend/dsl/commands/setup/{__init__,helpers,registers_domains,registers_integrations,registers_workflow,orchestrator}.py` (6 files)
- `src/backend/plugins/composition/lifecycle/lifespan.py` (1 file, 595 LOC)

### Modified (1 file)
- `src/backend/plugins/composition/lifecycle/__init__.py` (585 → 25 LOC, now thin re-exports)

### Deleted (3 dead files)
- `src/backend/dsl/processors/event_store.py`
- `src/backend/dsl/commands/setup.py`
- `src/backend/core/security/authorization_gateway.py` (sibling WIP from S60 W4)

## S49-S66 cumulative (18 sprints)

| Sprint | God-files fully closed | TDs closed |
|--------|------------------------|------------|
| S49-S65 | 59 | 6 |
| S66 | **+3** (event_store, setup, lifecycle/__init__) | — |
| **Total** | **62 god-files fully closed, 6 TDs closed** |

S66 alone: 2437 LOC → 18 well-organized files (sibling contributed 1 WIP fixup).

## S67+ candidates

Top remaining god-files (excluded migrations/versions/*.py autogenerated):
- `dsl/builders/base.py` 646 (RouteBuilder 32 methods, HIGH RISK — center of project)
- `core/resilience/backpressure.py` 465
- `core/ai/policy/enforcer.py` 462
- `services/ai/semantic_cache.py` 461
- `infrastructure/clients/external/express_bot.py` 461
- `dsl/blueprints/macros.py` 458
- `services/auth/ad_directory_client.py` 457

S66 закрыт. Total commits: 5 (4 working + closure).
