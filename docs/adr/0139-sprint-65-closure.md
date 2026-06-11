# ADR-0139 — Sprint 65 closure: 4 god-file decomp (components, rpa_operations, grpc_server, idp_pipeline) + 2 W3 sibling WIP fixups (4+1+2 commits, 7/7 substantive)

* Статус: Accepted (Sprint 65 W5, 2026-06-10)
* Связано с: 43004645 (W1), 7a698944 (W2), 70338fa5 + 75ad6066 + 50a1c12a (W3 + 2 fixups), 308c2ec1 (W4), this ADR (W5)
* Контекст: PLAN.md V22 final, S49-S64 pattern continuation

## Контекст

Sprint 65 закрыл 4 god-file:
- components.py 479 LOC (8 processor classes) — per-processor file split
- rpa/operations.py 478 LOC (9 processor classes) — per-processor file split
- grpc_server.py 480 LOC (3 servicers + 1 interceptor + 3 funcs) — per-concern file split
- idp_pipeline_processor.py 472 LOC (1 god-class 7 methods + 2 small + 10 funcs) — MRO + state + helpers

Plus 2 sibling-WIP fixups:
- config/base.py 485 LOC decomp (S65 W3) added `app_base_settings` and `scheduler_settings` instances to `__init__.py`

## Решения

1. **Per-processor file split (components.py, S65 W1)** — 8 processor classes → 8 files. **Critical fix**: must strip `@processor(...)` decorator block from `cleaned_imports` (S65 W1 fix). Decorator was multi-line (`@processor(\n  "http_call",\n  ...\n)`) and the walk-back logic needed to skip past the closing `)` to find the actual `@` line.

2. **Per-processor file split (rpa/operations.py, S65 W2)** — 9 processor classes → 9 files. Same `@processor` fix as W1.

3. **Per-concern file split (grpc_server.py, S65 W3)** — 3 servicers + 1 interceptor + 3 funcs → 5 files. Pre-existing sibling WIP `invoker_pb2` ModuleNotFoundError (protobuf generation issue, not my code).

4. **MRO + state + helpers (idp_pipeline_processor.py, S65 W4)** — 7 methods → 4 mixins (Pipeline 2 + Routing 1 + Serialization 1 + Helpers 2) + 1 core + state.py (2 small classes) + helpers.py (10 funcs). MRO 6-level.

5. **S65 W3 fixups (sibling WIP)** — Sibling's config/base decomp didn't preserve module-level instances. Added:
   - `app_base_settings: AppBaseSettings = AppBaseSettings()` to `__init__.py`
   - `scheduler_settings: SchedulerSettings = SchedulerSettings()` to `__init__.py`

## Изменения

| File | Before | After | Decomposition |
|------|--------|-------|----------------|
| components.py | 479 | 0 (deleted) | 8 processor classes → 8 files (per-processor split) |
| rpa/operations.py | 478 | 0 (deleted) | 9 processor classes → 9 files (per-processor split) |
| grpc_server.py | 480 | 0 (deleted) | 3 servicers + 1 interceptor + 3 funcs → 5 files (per-concern split) |
| idp_pipeline_processor.py | 472 | 0 (deleted) | 7 methods → 4 mixins + 1 core + state + helpers (MRO 6-level) |
| config/base.py (sibling) | 485 | 0 (deleted) | 2 classes → app_base + scheduler (sibling); fixup: add 2 module-level instances |
| **Total** | **2394** | **0 (replaced)** | **31 files created** |

## Quality gates (S65 scope)

- **mypy**: S65 changes clean (sibling WIP invoker_pb2 is pre-existing, not my code)
- **ruff**: clean for S65 changes
- Sibling WIP outstanding: 1800+ mypy errors (unchanged)

## Patterns re-used from S49-S64

- **MRO composition** (S49-S64 all MRO waves)
- **Per-concern file split** (S57 W4 sink_publish, S58 W3 format_converters, S59 W1 banking_processors, S60 W2 cdc, S62 W2 vocabulary, S63 W1 loading)
- **ABC + impl + factory split** (S55 W1 cert_store, S56 W3 s3_pool, S64 W2 repositories)
- **Strip `@processor(...)` block from cleaned_imports** (S65 W1 NEW)

## Lessons learned (для sprint-execution skill)

1. **Strip `@processor(...)` block from cleaned_imports** (S65 W1 NEW): when decomp'ing files with multi-line decorators before the first class, the walk-back logic must skip past the closing `)` to find the actual `@` line. If the walk-back breaks on the first non-empty line, it stops at the wrong place. Use: walk back through ALL non-@ lines (treating the @ line as the start).

2. **Module-level instances must be preserved in package decomp** (S65 W3 fixup): when a file has both classes and module-level instances (e.g., `app_base_settings: AppBaseSettings = AppBaseSettings()`), the decomp must preserve the instance. Otherwise 50+ callers break with `ImportError: cannot import name 'app_base_settings'`.

3. **Pre-existing sibling WIP: ignore and move on** (S65 W3): the `invoker_pb2` ModuleNotFoundError is a pre-existing protobuf generation issue, not caused by my decomp. Don't try to fix it; sibling owns.

## Files Modified

### Created (31 new files)
- `src/backend/dsl/engine/processors/components/{__init__,httpcallprocessor,databasequeryprocessor,filereadprocessor,filewriteprocessor,s3readprocessor,s3writeprocessor,timerprocessor,pollingconsumerprocessor}.py` (9 files)
- `src/backend/dsl/engine/processors/rpa/operations/{__init__,filemoveprocessor,archiveprocessor,imageocrprocessor,imageresizeprocessor,regexprocessor,templaterenderprocessor,hashprocessor,encryptprocessor,decryptprocessor}.py` (10 files)
- `src/backend/entrypoints/grpc/grpc_server/{__init__,base,order,invoker,interceptor,server}.py` (6 files)
- `src/backend/dsl/processors/idp_pipeline_processor/{__init__,pipeline_mixin,routing_mixin,serialization_mixin,helpers_mixin,state,helpers}.py` (7 files)

### Deleted (4 god-files)
- `src/backend/dsl/engine/processors/components.py`
- `src/backend/dsl/engine/processors/rpa/operations.py`
- `src/backend/entrypoints/grpc/grpc_server.py`
- `src/backend/dsl/processors/idp_pipeline_processor.py`

## S49-S65 cumulative (17 sprints)

| Sprint | God-files fully closed | TDs closed |
|--------|------------------------|------------|
| S49-S64 | 55 | 6 |
| S65 | **+4** (components, rpa_operations, grpc_server, idp_pipeline) | — |
| **Total** | **59 god-files fully closed, 6 TDs closed** |

S65 alone: 2394 LOC → 31 well-organized files (sibling contributed config/base + 3 WIP commits).

## S66+ candidates

Top remaining god-files:
- `setup.py` 854 (S53 W3 — 25 helpers + orchestrator)
- `builders/base.py` 646 (S57 W1 — RouteBuilder MRO 59-level)
- `lifecycle/__init__.py` 585 (S82 sibling)
- `setup_infra.py` 530 (S60 W3 — sibling re-created?)
- `event_store.py` 468 (8 classes + 3 funcs)

S65 закрыт. Total commits: 7 (4 working + 1 closure + 2 sibling fixups).
