# ADR-0137 — Sprint 63 closure: 4 god-file decomp (loading, routing, marshal, external_database) (4+1 commits, 5/5 substantive)

* Статус: Accepted (Sprint 63 W5, 2026-06-10)
* Связано с: 147352c2 (W1), f59ccc0b (W2), 06991c04 (W3), d220cbad (W4), this ADR (W5)
* Контекст: PLAN.md V22 final, S49-S62 pattern continuation

## Контекст

Sprint 63 закрыл 4 god-file:
- loading.py 496 LOC (LoadingMixin 5 methods + 2 small classes → 2 mixins + state.py)
- routing.py 496 LOC (6 EIP routing classes → 5 file split per routing pattern)
- marshal.py 494 LOC (8 classes + 3 helpers → 3 file split per concern)
- external_database.py 492 LOC (ExternalDatabaseService 16 methods + 1 small class + 2 funcs → 5 mixins + 1 core + state.py)

## Решения

1. **MRO without core + state.py (loading.py, S63 W1)** — 5 internal methods, no `__init__`. 2 mixins: LoaderMixin(2) + FrontendMixin(3). MRO 4-level (no core).

2. **Per-routing-pattern file split (routing.py, S63 W2)** — 6 EIP routing classes grouped by routing pattern: dynamic(1) + scatter_gather(1) + recipient_list(1) + load_balancer(1) + multicast(2).

3. **Base + formats + processors split (marshal.py, S63 W3)** — 8 classes + 3 helpers split into base(DataFormat) + formats(5 format classes + 3 helpers) + processors(MarshalProcessor, UnmarshalProcessor). Cross-imports: each format extends DataFormat; processors use both.

4. **MRO with 1 core + 5 mixins + state.py (external_database.py, S63 W4)** — 16 methods split into core_mixin(3) + dispatch_mixin(5) + validation_mixin(3) + build_mixin(3) + profile_mixin(1) + 1 core (__init__). MRO 7-level.

## Изменения

| File | Before | After | Decomposition |
|------|--------|-------|----------------|
| loading.py | 496 | 0 (deleted) | LoadingMixin 5 methods → 2 mixins + state.py (MRO 4-level, no core) |
| routing.py | 496 | 0 (deleted) | 6 classes → 5 files (per routing pattern) |
| marshal.py | 494 | 0 (deleted) | 8 classes + 3 helpers → base + formats + processors |
| external_database.py | 492 | 0 (deleted) | ExternalDatabaseService 16 methods → 5 mixins + 1 core + state.py (MRO 7-level) |
| **Total** | **1978** | **0 (replaced)** | **22 files created** |

## Quality gates (S63 scope)

- **mypy**: S63 changes clean
- **ruff**: clean for S63 changes
- Sibling WIP outstanding: 1700+ mypy errors

## Patterns re-used from S49-S62

- **MRO composition** (S49-S62 all MRO waves)
- **Per-concern file split** (S57 W4 sink_publish, S58 W3 format_converters, S59 W1 banking_processors, S60 W2 cdc, S62 W2 vocabulary)
- **MRO with no core methods** (S62 W3 NEW — applies to S63 W1)
- **Schemas/helpers/endpoints split** (S62 W1)
- **`@dataclass(slots=True)` conflict with mixin `__slots__ = ()`** (S57 W1 lesson)
- **`from __future__` deduplication + move to top** (S57 W1, S58 W2 lessons)

## Lessons learned (для sprint-execution skill)

1. **Helpers as top-level funcs in non-helpers file** (S63 W3 NEW): when extracting classes from a file with top-level helper funcs, manually add the funcs to the relevant split file (e.g., _json_default → formats.py). My AST extraction only captures classes; helpers need separate handling.

2. **Source method count vs inspection count** (S63 W4 lesson): re-count source methods with `ast` directly when in doubt. `inspect.getmembers` includes inherited methods from parent classes.

3. **Per-routing-pattern file split for EIP patterns** (S63 W2 NEW): EIP routing patterns (Dynamic/ScatterGather/RecipientList/LoadBalancer/Multicast) are each a distinct routing concept. Split by pattern, not by method count.

## Files Modified

### Created (22 new files)
- `src/backend/services/plugins/loader_v11/loading/{__init__,loader_mixin,frontend_mixin,state}.py` (4 files)
- `src/backend/dsl/engine/processors/eip/routing/{__init__,dynamic,scatter_gather,recipient_list,load_balancer,multicast}.py` (6 files)
- `src/backend/dsl/engine/processors/eip/marshal/{__init__,base,formats,processors}.py` (4 files)
- `src/backend/services/io/external_database/{__init__,core_mixin,dispatch_mixin,validation_mixin,build_mixin,profile_mixin,state}.py` (7 files)

### Deleted (4 god-files)
- `src/backend/services/plugins/loader_v11/loading.py`
- `src/backend/dsl/engine/processors/eip/routing.py`
- `src/backend/dsl/engine/processors/eip/marshal.py`
- `src/backend/services/io/external_database.py`

## S49-S63 cumulative (15 sprints)

| Sprint | God-files fully closed | TDs closed |
|--------|------------------------|------------|
| S49-S62 | 47 | 6 |
| S63 | **+4** (loading, routing, marshal, external_database) | — |
| **Total** | **51 god-files fully closed, 6 TDs closed** |

S63 alone: 1978 LOC → 22 well-organized files.

## S64+ candidates

Top remaining god-files:
- `setup.py` 870 (S53 W3 — 25 helpers + orchestrator)
- `builders/base.py` 648 (S57 W1 — RouteBuilder MRO 59-level)
- `lifecycle/__init__.py` 585 (S59 W2 SKIPPED — sibling W82)
- `setup_infra.py` 534 (S60 W3 — sibling re-created?)
- `graphql/schema.py` 492
- `repositories/base.py` 491
- `database.py` 489
- (and many more in 480-490 range)

S63 закрыт. Total commits: 5 (4 working + 1 closure).
