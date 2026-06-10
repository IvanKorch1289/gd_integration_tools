# ADR-0135 — Sprint 61 closure: 4 god-file decomp (base_service, enrichment, executor, http) (4+1 commits, 5/5 substantive)

* Статус: Accepted (Sprint 61 W5, 2026-06-10)
* Связано с: 58ef1342 (W1), 71812248 (W2), b51d020c (W3), 995da79f (W4), this ADR (W5)
* Контекст: PLAN.md V22 final, S49-S60 pattern continuation

## Контекст

Sprint 61 закрыл 4 god-file:
- services/core/base.py 526 LOC (BaseService 16 methods + 3 top-level funcs → 3 mixins + 4 core + helpers.py)
- enrichment.py 523 LOC (8 processor classes → 5 file split per enrichment type)
- executor.py 514 LOC (DSLStepExecutor 10 methods + 3 small classes → 4 mixins + 2 core + state.py)
- http.py 514 LOC (HttpClient 17 methods + 2 small classes + 2 funcs → 4 mixins + 2 core + base.py + factory.py)

## Решения

1. **Per-concern MRO with helpers (base_service.py, S61 W1)** — 16 methods split into cache(1) + crud(7) + versioning(4) + 4 core. Generic class type params `BaseService[Repo, Response, Request, Version]` preserved. Top-level funcs in `helpers.py`.

2. **Per-enrichment file split (enrichment.py, S61 W2)** — 8 small processor classes grouped by similarity: geo_ip(1) + jwt(2) + compression(2) + webhook(2) + deadline(1).

3. **DSL step executor MRO + state (executor.py, S61 W3)** — 10 methods split into sequential(1) + control_flow(3) + sub_flow(2) + eval(2) + 2 core. 3 small classes (WorkflowStep, WorkflowSpec, DurableWorkflowProcessor) in state.py.

4. **HTTP client MRO + base + factory (http.py, S61 W4)** — 17 methods split into session(5) + request(3) + prep(3) + observability(4) + 2 core. ABC `BaseHttpClient` + multipart `FilePart` in base.py. Factory funcs in factory.py.

## Изменения

| File | Before | After | Decomposition |
|------|--------|-------|----------------|
| services/core/base.py | 526 | 0 (deleted) | BaseService 16 methods → 3 mixins + 4 core + helpers.py (MRO 5-level, generic class) |
| enrichment.py | 523 | 0 (deleted) | 8 classes → 5 files (per enrichment type) |
| executor.py | 514 | 0 (deleted) | DSLStepExecutor 10 methods → 4 mixins + 2 core + state.py (MRO 6-level) |
| http.py | 514 | 0 (deleted) | HttpClient 17 methods → 4 mixins + 2 core + base.py + factory.py (MRO 6-level) |
| **Total** | **2077** | **0 (replaced)** | **22 files created** |

## Quality gates (S61 scope)

- **mypy**: S61 changes clean
- **ruff**: clean for S61 changes
- Sibling WIP outstanding: 1700+ mypy errors (Redis WIP `redis_client` import still broken)

## Patterns re-used from S49-S60

- **MRO composition** (S49-S60 all MRO waves)
- **Per-concern file split** (S57 W4 sink_publish, S58 W3 format_converters, S59 W1 banking_processors, S60 W2 cdc)
- **Generic class type params preservation** (S61 W1 NEW pattern)
- **Helper files for small classes** (S58 W2 saga_lra_processor, S60 W1 jupyter, S61 W3 executor)
- **`@dataclass(slots=True)` conflict with mixin `__slots__ = ()`** (S57 W1 lesson)
- **`from __future__` deduplication + move to top** (S57 W1, S58 W2 lessons)

## Lessons learned (для sprint-execution skill)

1. **Generic class type params preservation** (S61 W1 NEW): when decomp'ing `class BaseService[A, B, C, D]:`, find the class header by counting brackets — find line where `]` closes and `]:` ends the header. The class header can span multiple lines if there are many type params. Pass the entire header through verbatim.

2. **Use `.venv/bin/python` explicitly for AST parsing** (S61 W1 lesson): the `execute_code` tool uses `/bin/python` (3.12) by default, but the venv has 3.14. Python 3.12+ generic class syntax `class Foo[T]` works in 3.12 but error messages can be confusing. Always use `subprocess.run(['.venv/bin/python', ...])` for AST parsing of files with 3.12+ syntax.

3. **Sibling WIP `redis_client` import still broken** (S60 W3 → S61 W1 lesson continued): the `from src.backend.infrastructure.clients.storage.redis import redis_client` is broken in sibling WIP. Multiple waves (S60 W3, S61 W1) have run into this. Don't try to fix it — sibling owns it.

4. **Per-mixin-slot-pattern from S60 → S61 W1**: `__slots__ = ()` is a common pattern. Always strip `@dataclass(slots=True)` from each mixin (or the `__slots__ = ()` in the class body), otherwise mypy/ruff errors.

## Files Modified

### Created (22 new files)
- `src/backend/services/core/base/{__init__,cache_mixin,crud_mixin,versioning_mixin,helpers}.py` (5 files)
- `src/backend/dsl/engine/processors/enrichment/{__init__,geo_ip,jwt,compression,webhook,deadline}.py` (6 files)
- `src/backend/infrastructure/workflow/executor/{__init__,sequential_mixin,control_flow_mixin,sub_flow_mixin,eval_mixin,state}.py` (6 files)
- `src/backend/infrastructure/clients/transport/http/{__init__,session_mixin,request_mixin,prep_mixin,observability_mixin,base,factory}.py` (7 files)

### Deleted (4 god-files)
- `src/backend/services/core/base.py`
- `src/backend/dsl/engine/processors/enrichment.py`
- `src/backend/infrastructure/workflow/executor.py`
- `src/backend/infrastructure/clients/transport/http.py`

## S49-S61 cumulative (13 sprints)

| Sprint | God-files fully closed | TDs closed |
|--------|------------------------|------------|
| S49-S60 | 39 | 6 |
| S61 | **+4** (base_service, enrichment, executor, http) | — |
| **Total** | **43 god-files fully closed, 6 TDs closed** |

S61 alone: 2077 LOC → 22 well-organized files.

## S62+ candidates

| Task | Effort | Notes |
|------|--------|-------|
| (need fresh top-10 scan) | — | S62 plan |
| TD-006 / TD-005 / TD-008 | analysis | low risk |
| Sibling WIP push | — | 1700+ mypy errors |

S61 закрыт. Total commits: 5 (4 working + 1 closure).
