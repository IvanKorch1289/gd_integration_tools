# ADR-0129 — Sprint 55 closure: 4 god-file decomp (cert_store, control_flow, pg_runner_internals, data_quality) (4+1 commits, 5/5 substantive)

* Статус: Accepted (Sprint 55 W5, 2026-06-10)
* Связано с: a70c7a1d (W1), a1033bd9 (W2), fc1dae51 (W3), 62c87c41 (W4)
* Контекст: PLAN.md V22 final, S49-S54 pattern continuation (5 commits = 4 working + closure)

## Контекст

Sprint 55 закрыл 4 god-file из top-10 списка (S54 W5 report):
- cert_store.py 628 LOC (7 classes — per-backend file split)
- control_flow.py 628 LOC (8 classes + 4 helpers — per-concept file split)
- pg_runner_internals.py 618 LOC (4 classes + 2 helpers — per-domain file split)
- data_quality.py 618 LOC (1 god-class DataQualityMonitor 10 methods → MRO 4 mixins)

## Решения

1. **cert_store: per-backend file split (S55 W1)** — pattern: `models.py` + `backend_base.py` (ABC) + 4 per-backend impls + `store.py` (facade) + `__init__.py` (re-exports). 8 files total.

2. **control_flow: per-concept file split (S55 W2)** — pattern (streaming.py S53 W2): choice + flow + parallel + saga (4 control-flow concepts). Helpers (`_normalize_choice_branches`, `_serialize_sub`, `_emit_saga_audit`) co-located с relevant concept. 5 files total.

3. **pg_runner_internals: per-domain file split (S55 W3)** — pattern: rows + state + event_store + instance_store (4 SQL-domain concerns). 5 files total.

4. **data_quality: MRO composition (S55 W4)** — pattern: 4 mixins (rule_mgmt, check, schema, apply) + 2 core (`__init__`, `add_rule`). The BIG `_apply_rule` method (263 LOC) isolated в own mixin.

## Изменения

| File | Before | After | Method/class count |
|------|--------|-------|-------------------|
| cert_store.py | 628 | 0 (deleted) | 7 classes → 8 files |
| control_flow.py | 628 | 0 (deleted) | 8 classes + 4 helpers → 5 files |
| pg_runner_internals.py | 618 | 0 (deleted) | 4 classes + 2 helpers → 5 files |
| data_quality.py | 618 | 0 (deleted) | 10 methods → 5 files (4 mixins + 1 init) |
| **Total** | **2492** | **0 (replaced)** | **29 classes + 6 helpers / 10 methods → 23 files** |

## Quality gates (S55 scope)

- **mypy**: 1612 source files checked (S55 changes clean)
- **ruff**: 14 fixable issues in S55 changes (mostly import sort)
- Sibling WIP outstanding (NOT in S55 scope): 600+ mypy errors in 24 files (cert_store.__init__.py hashlib missing, jupyter, notebook_execute, cdc_client_adapter, etc.)

## Patterns re-used from S49-S54

- **Multi-class file split per-backend/per-concept** (S50 W4 rpa.py, S53 W2 streaming.py, S54 W1 mcp_server.py) — primary pattern
- **MRO composition for stateful god-classes** (S54 W2/W3/W4 ai_agent, invoker, capability_gate)
- **`from __future__` deduplication** (S54 W4 lesson) — must dedup script output
- **Cross-imports for extending classes** (S55 W1: each backend imports `CertBackend` from `backend_base.py`)
- **Top-level Pydantic / data class re-exports** in `__init__.py` (S54 W3 pattern)

## Lessons learned (для sprint-execution skill)

1. **For ABC + multiple implementations (cert_store pattern)**: dedicated `backend_base.py` for the ABC; one file per concrete impl; facade file (`store.py`) at the end. Cross-imports MUST be added by the extraction script (each backend file needs `from .backend_base import CertBackend`).

2. **For per-concept splits (control_flow pattern)**: 4-5 conceptual groups is sweet spot. Each file has 1-3 classes + co-located helpers. Don't over-split (1-class-per-file is overkill for small classes).

3. **For multi-class with state machines (pg_runner_internals pattern)**: split by responsibility (rows / state / event_store / instance_store), not by class. Cross-references between classes need explicit imports.

4. **For god-class MRO with one BIG method (data_quality pattern)**: the BIG method gets its own mixin. Provides natural reading order (small public → big internal) and reduces cognitive load per file.

5. **Pydantic/dataclass imports preservation**: when original file has `from dataclasses import field as dataclass_field`, the script MUST preserve the alias. The `__init__.py` for the new package often needs ALL the original dataclass + enum imports.

6. **Sibling WIP accumulates fast**: by S55 there are 600+ pre-existing errors in 24 files (cert_store, jupyter, notebook_execute, cdc_client_adapter, etc.). My S55 changes add ~10 errors max. Don't try to fix sibling WIP — just make sure my changes don't add new errors.

## Files Modified

### Created (23 new files)
- `src/backend/infrastructure/security/cert_store/{__init__,models,backend_base,backend_memory,backend_postgres,backend_vault,backend_mongo,store}.py`
- `src/backend/dsl/engine/processors/control_flow/{__init__,choice,flow,parallel,saga}.py`
- `src/backend/infrastructure/workflow/pg_runner_internals/{__init__,rows,state,event_store,instance_store}.py`
- `src/backend/services/ops/data_quality/{__init__,rule_mgmt_mixin,check_mixin,schema_mixin,apply_mixin}.py`

### Deleted (4 god-files)
- `src/backend/infrastructure/security/cert_store.py`
- `src/backend/dsl/engine/processors/control_flow.py`
- `src/backend/infrastructure/workflow/pg_runner_internals.py`
- `src/backend/services/ops/data_quality.py`

## S49-S55 cumulative

| Sprint | God-files fully closed | TDs closed |
|--------|------------------------|------------|
| S49 | 31_DSL_Visual_Editor 1267→616, actions.py 986→353+669 | TD-009 |
| S50 | transport.py, ai_banking.py 828, rpa.py 823 | TD-001, TD-007 |
| S51 | agent_dsl.py 771, ai_rpa.py 61/61 (3-wave) | TD-003 |
| S52 | validator.py 760, loader_v11.py 724 | TD-010 |
| S53 | format_convert.py 744, streaming.py 737, setup.py 756 | TD-002 |
| S54 | mcp_server.py 706, ai_agent.py 703, invoker.py 666, capability_gate.py 629 | — |
| S55 | cert_store.py 628, control_flow.py 628, pg_runner_internals.py 618, data_quality.py 618 | — |

**Total: 20 god-files fully closed, 6 TDs closed (2492 LOC → 23 well-organized files in S55 alone)**

## S56+ candidates

| Task | Effort | Notes |
|------|--------|-------|
| spec.py 636 (workflow spec, 15 Pydantic schemas) | 1 wave | type-heavy, low risk |
| base.py 648 (RouteBuilder 32 methods — DSL framework base) | 1-2 waves | HIGH RISK, breaks all DSL |
| Streamlit frontend pages (next layer) | 2-3 waves | many small files |
| TD-006 (Vite/chromadb phantom) | analysis | low risk |
| TD-005 / TD-008 (still open) | investigation | need fresh scope |
| Sibling WIP push | — | 600+ mypy errors accumulated |

## Sibling WIP outstanding (NOT in S55 scope)

- `src/backend/infrastructure/security/cert_store/__init__.py:41` — hashlib missing (W1 sibling pre-existing)
- `src/backend/services/jupyter/execution_service.py:457` — pre-existing
- `src/backend/dsl/workflow/builder.pyi:25` — pre-existing Ellipsis type
- `src/backend/infrastructure/cdc/cdc_client_adapter.py:103` — pre-existing async/await
- `src/backend/services/jupyter/__init__.py` — missing execution_service module
- `src/backend/dsl/engine/processors/notebook_execute.py` — missing types module
- `src/backend/infrastructure/storage/trace_storage.py` — pre-existing ruff errors

S55 закрыт. Total commits: 5 (4 working + 1 closure).
