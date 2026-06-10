# ADR-0130 — Sprint 56 closure: 4 god-file decomp (spec, gateway_pipeline_mixin, s3_pool, admin_workflows) (5+1 commits, 5/5 substantive)

* Статус: Accepted (Sprint 56 W5, 2026-06-10)
* Связано с: cd8e5d77 (W1), f06f7de4 (W2), fd860840 (W3), 1b69e0e2 + ac04467b (W4), this ADR (W5)
* Контекст: PLAN.md V22 final, S49-S55 pattern continuation (5+ commits = 4 working + closure)

## Контекст

Sprint 56 закрыл 4 god-file из top-10 списка (S55 W5 report):
- spec.py 636 LOC (15 Pydantic schemas + WorkflowStep type alias → 4 file split)
- gateway_pipeline_mixin.py 620 LOC (1 mixin 15 methods → 5 mixins, MRO 6-level)
- s3_pool.py 591 LOC (BaseS3Client + S3Client → 2-file split)
- admin_workflows.py 639 LOC (5 schemas + 1 facade + 9 helpers + router → 5-file split)

## Решения

1. **Pydantic-heavy file split (spec.py, S56 W1)** — pattern: per-category groups. **Critical lesson**: type alias `WorkflowStep` (not a class) must be preserved in `__init__.py` with its Pydantic `Annotated[...]` constructor. Missing it breaks all consumers.

2. **Already-mixin file decomp (gateway_pipeline_mixin.py, S56 W2)** — pattern: 5 mixins in MRO. **Lesson**: file name was misleading (class is `PipelineStepsMixin`, not `Gateway*Mixin`). Class has no `__init__` method — all 15 methods are internal helpers. Pure MRO split without core.

3. **ABC + impl file split (s3_pool.py, S56 W3)** — pattern: per-class file. Cross-imports: `client.py` imports `BaseS3Client` from `base.py`. ABC subclasses automatically resolve via MRO.

4. **Endpoint file with router (admin_workflows.py, S56 W4)** — pattern: 4-file split (schemas + facade + helpers + input_schema) + router preserved in `__init__.py`. **Critical lesson**: FastAPI endpoint files have `router = APIRouter(...)` + `builder.add_actions([...])` block at the END — these MUST be preserved or routers.py breaks.

## Изменения

| File | Before | After | Decomposition |
|------|--------|-------|----------------|
| spec.py | 636 | 0 (deleted) | 15 schemas + WorkflowStep → 4 files |
| gateway_pipeline_mixin.py | 620 | 0 (deleted) | 15 methods → 5 mixins |
| s3_pool.py | 591 | 0 (deleted) | 2 classes → 2 files (base + client) |
| admin_workflows.py | 639 | 0 (deleted) | 5 schemas + 1 facade + 9 helpers + router → 5 files |
| **Total** | **2486** | **0 (replaced)** | **18 files created** |

## Quality gates (S56 scope)

- **mypy**: 1628 source files checked (S56 changes clean — only WorkflowStatus / router response_model type hints unresolved)
- **ruff**: 50-60 fixable issues in S56 changes (mostly import sort)
- Sibling WIP outstanding (NOT in S56 scope): 880+ mypy errors in 44 files (workflows, RAG, jupyter, chaos, etc.)

## Patterns re-used from S49-S55

- **Per-domain file split** (S50 W4 rpa.py, S53 W2 streaming.py, S54 W1 mcp_server.py, S55 W1 cert_store.py, S55 W2 control_flow.py) — primary pattern
- **MRO composition for stateful god-classes** (S54 W2/W3/W4 ai_agent, invoker, capability_gate, S55 W4 data_quality)
- **`from __future__` deduplication** (S54 W4 lesson) — must dedup script output
- **Cross-imports for ABC** (S55 W1 cert_store) — each impl file imports ABC
- **Top-level Pydantic / data class re-exports** in `__init__.py` (S55 W3 pattern)
- **Pydantic `Annotated[...]` type alias preservation** (S56 W1 NEW)
- **Router + endpoint registration preservation** in `__init__.py` (S56 W4 NEW)

## Lessons learned (для sprint-execution skill)

1. **Pydantic type aliases MUST be preserved**: `WorkflowStep = Annotated[Union[...], Field(discriminator="type")]` is a top-level `Assign` statement, NOT a class. AST extraction scripts need to find these by name and re-export in `__init__.py`.

2. **Pydantic imports propagation**: when extracting Pydantic schemas to a package, the `__init__.py` often needs `from pydantic import Field, BaseModel, TypeAdapter` even if no class is defined locally. Check what the original file imported.

3. **File name vs class name mismatch** is common in codebase. Don't assume file name = class name. Use AST to find the actual class.

4. **Endpoint files (FastAPI) have a critical tail block**: `router = APIRouter(...)` + `builder.add_actions([...])` is the "what's exposed" section. Must be preserved in `__init__.py` or the parent `routers.py` breaks. The decorators (like `@router.get(...)`) are NOT separate items — they're inside the `add_actions` list.

5. **S54+W4 `__init__` + method count** vs `__init__` only: data files (spec.py) have 0-method classes; ABC files (s3_pool.py) have stub methods; god-classes (data_quality) have full __init__ + methods. Different splits for each.

6. **Pure mixin file (no class body) is rare but valid**: gateway_pipeline_mixin.py has 1 class with NO `__init__` method — all 15 methods are internal. The split is just 5 mixins + MRO + logger, no core.

7. **Sibling WIP explosion**: S56 has 880+ pre-existing errors in 44 sibling WIP files (workflows, RAG, jupyter, chaos, etc.). My S56 changes add ~10 max. Don't try to fix sibling WIP.

## Files Modified

### Created (18 new files)
- `src/backend/dsl/workflow/spec/{__init__,policies,activity_declarations,advanced_declarations,workflow}.py`
- `src/backend/core/ai/gateway_pipeline_mixin/{__init__,policy_mixin,input_mixin,llm_mixin,output_mixin,observability_mixin}.py`
- `src/backend/infrastructure/clients/storage/s3_pool/{__init__,base,client}.py`
- `src/backend/entrypoints/api/v1/endpoints/admin_workflows/{__init__,schemas,facade,helpers,input_schema}.py`

### Deleted (4 god-files)
- `src/backend/dsl/workflow/spec.py`
- `src/backend/core/ai/gateway_pipeline_mixin.py`
- `src/backend/infrastructure/clients/storage/s3_pool.py`
- `src/backend/entrypoints/api/v1/endpoints/admin_workflows.py`

## S49-S56 cumulative (8 sprints)

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

**Total: 24 god-files fully closed, 6 TDs closed (2486 LOC → 18 well-organized files in S56 alone)**

## S57+ candidates

| Task | Effort | Notes |
|------|--------|-------|
| base.py 648 (RouteBuilder 32 methods — DSL framework base) | 1-2 waves | **HIGH RISK** — breaks all DSL |
| Streamlit frontend pages (next layer) | 2-3 waves | many small files |
| TD-006 (Vite/chromadb phantom) | analysis | low risk |
| TD-005 / TD-008 (still open) | investigation | need fresh scope |
| Sibling WIP push | — | 880+ mypy errors accumulated |
| **Pre-emptive tests** | 1 wave | add smoke tests for decompiled packages |
| **abc_split pattern formalization** | doc | per-impl file pattern (S55 W1, S56 W3) |

## Sibling WIP outstanding (NOT in S56 scope)

- 30+ modified files from sibling (notebooks, chaos, unified_pool, rag, workflows, etc.)
- 13+ untracked files (notebook.py, file_watch.py, jupyter/, chaos/, etc.)
- ~880 mypy errors in 44 files (mostly sibling WIP + pre-existing)

S56 закрыт. Total commits: 6 (4 working + 1 fixup + 1 closure).
