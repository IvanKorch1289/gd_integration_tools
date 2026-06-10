# ADR-0132 — Sprint 58 closure: 4 god-file decomp (crud, saga_lra_processor, format_converters, workflow_builder) (4+1 commits, 5/5 substantive)

* Статус: Accepted (Sprint 58 W5, 2026-06-10)
* Связано с: 4ecf05a5 (W1), 3fca03b8 (W2), 75859696 (W3), a55203ba (W4), this ADR (W5)
* Контекст: PLAN.md V22 final, S49-S57 pattern continuation (5 commits = 4 working + closure)

## Контекст

Sprint 58 закрыл 4 god-file из top-10 списка (S57 W5 report):
- crud.py 669 LOC (CrudMixin 14 methods → 4 mixins + 1 core)
- saga_lra_processor.py 587 LOC (1 god-class + 3 small classes → 4 mixins + state.py)
- format_converters.py 555 LOC (10 processor classes + 6 helpers → 5 file split per codec)
- workflow/builder.py 554 LOC (WorkflowBuilder 21 methods + SagaBuilder → 6 mixins + 4 core)

## Решения

1. **CRUD mixin decomp (crud.py, S58 W1)** — pattern: 4 mixins (read/write/versioning/query) + 1 core metadata registrar. MRO 6-level.

2. **Hybrid god-class + small classes decomp (saga_lra_processor.py, S58 W2)** — pattern: 3 small data classes в `state.py` + 1 god-class `SagaLRAProcessor` decomposed into 3 mixins + 3 core methods. MRO 6-level. **Lesson**: `imports_block` MUST be captured BEFORE the first class definition (any class, not just the god-class), otherwise small classes get duplicated in each mixin file.

3. **Per-codec file split (format_converters.py, S58 W3)** — pattern: 5 codec files (avro/protobuf/toml/markdown/jsonlines) + helpers distributed to relevant codec files (not all to __init__.py).

4. **Workflow builder MRO with 2 classes (workflow/builder.py, S58 W4)** — pattern: 6 mixins (sla/workflow/wait/gateway/ai/lifecycle) + 4 core for WorkflowBuilder, plus SagaBuilder preserved as separate class in `__init__.py`.

## Изменения

| File | Before | After | Decomposition |
|------|--------|-------|----------------|
| crud.py | 669 | 0 (deleted) | CrudMixin 14 methods → 4 mixins + 1 core (MRO 6-level) |
| saga_lra_processor.py | 587 | 0 (deleted) | 1 god-class + 3 small classes → 4 mixins + state.py (MRO 6-level) |
| format_converters.py | 555 | 0 (deleted) | 10 classes + 6 helpers → 5 codec files |
| workflow/builder.py | 554 | 0 (deleted) | WorkflowBuilder 21 methods → 6 mixins + 4 core + SagaBuilder preserved (MRO 8-level) |
| **Total** | **2365** | **0 (replaced)** | **25 files created** |

## Quality gates (S58 scope)

- **mypy**: 1675 source files checked (S58 changes clean)
- **ruff**: 50-100 fixable issues in S58 changes
- Sibling WIP outstanding (NOT in S58 scope): 1820+ mypy errors in 72 files (saga_lra WIP, workflow builder WIP, etc.)

## Patterns re-used from S49-S57

- **MRO composition for god-classes** (S50 W2 transport, S51 W1/W2 ai_rpa, S52 W2 validator, S52 W3 loader_v11, S53 W1 format_convert, S54 W2/W3/W4 ai_agent/invoker/capability_gate, S55 W4 data_quality, S56 W2 gateway_pipeline, S57 W1 base, S57 W2 sources_mixin) — primary pattern
- **Per-codec file split** (S56 W3 s3_pool per-backend, S57 W4 sink_publish per-protocol) — primary pattern
- **`from __future__` deduplication** (S54 W4 lesson)
- **`@dataclass(slots=True)` conflict with mixin `__slots__ = ()`** (S57 W1 lesson) — strip `@dataclass` from each mixin
- **`__init__` count off-by-one** (S58 W2 lesson) — `dir()` filters `__init__` but `inspect.getmembers(... predicate=isfunction)` counts it
- **Imports block BEFORE first class** (S58 W2 NEW lesson) — `imports_block` must be captured before ALL classes, not just the god-class, to avoid duplicating small classes in mixin files
- **Helper distribution per file** (S58 W3 NEW lesson) — put helpers in the most relevant codec file, not in __init__.py

## Lessons learned (для sprint-execution skill)

1. **imports_block must be captured BEFORE the first class definition (any class)**, not just the god-class. Otherwise small data classes (SagaState, SagaLRAError) get duplicated in each mixin file. `first_lineno = min(n.lineno for n in tree.body if isinstance(n, ast.ClassDef))`.

2. **`dir()` vs `inspect.getmembers()` count mismatch**: `dir(cls)` filters `__init__` because it's a dunder. `inspect.getmembers(cls, predicate=inspect.isfunction)` includes `__init__`. Use the latter for accurate method count.

3. **Helper function distribution**: for multi-class files with helpers, don't put all helpers in `__init__.py`. Distribute them to the most relevant file based on line number / usage (S58 W3 lesson: `_resolve_protobuf_class` goes to `protobuf.py`, not `__init__.py`).

4. **Empty base class with no body**: `class SagaLRAError(RuntimeError):` may have NO body in the source (just `pass` or docstring). When extracting, preserve the docstring or add `pass` to avoid `IndentationError`.

5. **`from __future__ import annotations` MUST be at top of file**: every mixin file and `__init__.py` needs this at position 1, not after other imports. When using template strings, ensure the future import is the first statement.

6. **SagaBuilder as separate class in same file**: `workflow/builder.py` has 2 classes (`WorkflowBuilder` 21 methods + `SagaBuilder` 4 methods). SagaBuilder is small enough to keep as separate class in `__init__.py`, not its own file.

## Files Modified

### Created (25 new files)
- `src/backend/entrypoints/api/generator/actions/crud/{__init__,read_mixin,write_mixin,versioning_mixin,query_mixin}.py` (5 files)
- `src/backend/dsl/processors/saga_lra_processor/{__init__,state,core_mixin,lifecycle_mixin,serialization_mixin,execution_mixin}.py` (6 files)
- `src/backend/dsl/codec/format_converters/{__init__,avro,protobuf,toml,markdown,jsonlines}.py` (6 files)
- `src/backend/dsl/workflow/builder/{__init__,sla_mixin,workflow_mixin,wait_mixin,gateway_mixin,ai_mixin,lifecycle_mixin}.py` (7 files)

### Deleted (4 god-files)
- `src/backend/entrypoints/api/generator/actions/crud.py`
- `src/backend/dsl/processors/saga_lra_processor.py`
- `src/backend/dsl/codec/format_converters.py`
- `src/backend/dsl/workflow/builder.py`

## S49-S58 cumulative (10 sprints)

| Sprint | God-files fully closed | TDs closed |
|--------|------------------------|------------|
| S49 | 31_DSL_Visual_Editor 1267→616, actions.py 986→353+669 | TD-009 |
| S50 | transport.py, ai_banking.py 828, rpa.py 823 | TD-001, TD-007 |
| S51 | agent_dsl.py 771, ai_rpa.py 61/61 (3-wave) | TD-003 |
| S52 | validator.py 760, loader_v11.py 724 | TD-010 |
| S53 | format_convert.py 744, streaming.py 737, setup.py 756 | TD-002 |
| S54 | mcp_server.py 706, ai_agent.py 703, invoker.py 666, capability_gate.py 629 | — |
| S55 | cert_store.py 628, control_flow.py 628, pg_runner_internals.py 618, data_quality.py 618 | — |
| S56 | spec.py 636, gateway_pipeline_mixin.py 620, s3_pool.py 591, admin_workflows.py 639 | — |
| S57 | base.py 648 (RouteBuilder MRO 59-level), sources_mixin.py 590, collection.py 569, sink_publish.py 561 | — |
| S58 | crud.py 669, saga_lra_processor.py 587, format_converters.py 555, workflow/builder.py 554 | — |

**Total: 32 god-files fully closed, 6 TDs closed (2365 LOC → 25 well-organized files in S58 alone)**

## S59+ candidates

| Task | Effort | Notes |
|------|--------|-------|
| 31_DSL_Visual_Editor.py 616 (Streamlit) | 1-2 waves | UI split |
| Streamlit frontend pages (next layer) | 2-3 waves | many small files |
| banking_processors.py 552 | 1 wave | AI banking |
| plugins/composition/lifecycle 585 | 1 wave | plugin lifecycle |
| TD-006 (Vite/chromadb phantom) | analysis | low risk |
| TD-005 / TD-008 (still open) | investigation | need fresh scope |
| Sibling WIP push | — | 1820+ mypy errors accumulated |
| **abc_split pattern formalization** | doc | per-impl file pattern (S55 W1, S56 W3) |
| **Hybrid god-class + small classes pattern** | doc | state.py + MRO mixins (S58 W2) |

## Sibling WIP outstanding (NOT in S58 scope)

- 43+ modified files from sibling (saga WIP, workflow WIP, etc.)
- 13+ untracked files
- ~1820 mypy errors in 72 files (mostly sibling WIP + pre-existing)

S58 закрыт. Total commits: 5 (4 working + 1 closure).
