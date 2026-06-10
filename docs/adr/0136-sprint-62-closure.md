# ADR-0136 — Sprint 62 closure: 4 god-file decomp (admin_plugins, vocabulary, integration_core, yaml_loader) (4+1 commits, 5/5 substantive)

* Статус: Accepted (Sprint 62 W5, 2026-06-10)
* Связано с: f0028f2a (W1), 33ce7788 (W2), 5f3b53aa (W3), 6fec4ccf (W4), this ADR (W5)
* Контекст: PLAN.md V22 final, S49-S61 pattern continuation

## Контекст

Sprint 62 закрыл 4 god-file:
- admin_plugins.py 514 LOC (11 schemas + 13 funcs → schemas + helpers + endpoints)
- vocabulary.py 509 LOC (2 classes + 1 BIG function → models + vocabulary + defaults)
- integration_core.py 498 LOC (IntegrationCoreMixin 15 methods → 4 mixins)
- yaml_loader.py 495 LOC (10 top-level funcs → 4 file split)

## Решения

1. **Schemas/helpers/endpoints split (admin_plugins.py, S62 W1)** — 11 Pydantic schemas + 13 funcs. 4 file split: schemas(11) + helpers(5) + endpoints(8).

2. **Models + class + BIG function (vocabulary.py, S62 W2)** — CapabilityDef (data) + CapabilityVocabulary (7 methods class) + build_default_vocabulary (388 LOC BIG). 4 file split with cross-imports.

3. **MRO with no core (integration_core.py, S62 W3)** — 15 public methods, no `__init__` or helpers. 4 mixins: core_dispatch(3) + workflow_ops(3) + utils(7) + ai_ops(2). MRO 6-level.

4. **Top-level funcs split (yaml_loader.py, S62 W4)** — 10 funcs split into resolve(2) + loaders(3) + build(4) + control_flow(1). _resolve_include_extends is 153 LOC BIG.

## Изменения

| File | Before | After | Decomposition |
|------|--------|-------|----------------|
| admin_plugins.py | 514 | 0 (deleted) | 11 schemas + 13 funcs → schemas + helpers + endpoints |
| vocabulary.py | 509 | 0 (deleted) | 2 classes + 1 BIG function → models + vocabulary + defaults |
| integration_core.py | 498 | 0 (deleted) | 15 methods → 4 mixins (MRO 6-level, no core) |
| yaml_loader.py | 495 | 0 (deleted) | 10 funcs → resolve + loaders + build + control_flow |
| **Total** | **2016** | **0 (replaced)** | **17 files created** |

## Quality gates (S62 scope)

- **mypy**: S62 changes clean
- **ruff**: clean for S62 changes
- Sibling WIP outstanding: 1700+ mypy errors

## Patterns re-used from S49-S61

- **MRO composition** (S49-S61 all MRO waves)
- **Per-concern file split** (S57 W4 sink_publish, S58 W3 format_converters, S59 W1 banking_processors, S60 W2 cdc)
- **MRO with no core methods** (S62 W3 NEW): when all 15 methods are public, no `__init__`/core needed
- **Schemas/helpers/endpoints split for API endpoints** (S56 W4 admin_workflows, S62 W1 admin_plugins)

## Lessons learned (для sprint-execution skill)

1. **MRO with no core methods** (S62 W3 NEW): when decomp'ing a class with only public methods (no `__init__`, no internal helpers), the MRO chain is just the mixins. The class body becomes empty (just `__slots__ = ()`).

2. **Schemas/helpers/endpoints pattern is repeatable** (S62 W1): for FastAPI endpoint files with schemas + funcs, the cleanest split is 3 files (schemas + helpers + endpoints). The endpoints file imports from schemas.

## Files Modified

### Created (17 new files)
- `src/backend/entrypoints/api/v1/endpoints/admin_plugins/{__init__,schemas,helpers,endpoints}.py` (4 files)
- `src/backend/core/security/capabilities/vocabulary/{__init__,models,vocabulary,defaults}.py` (4 files)
- `src/backend/dsl/builders/integration_core/{__init__,core_mixin,workflow_mixin,utils_mixin,ai_mixin}.py` (5 files)
- `src/backend/dsl/yaml_loader/{__init__,resolve,loaders,build,control_flow}.py` (5 files)

### Deleted (4 god-files)
- `src/backend/entrypoints/api/v1/endpoints/admin_plugins.py`
- `src/backend/core/security/capabilities/vocabulary.py`
- `src/backend/dsl/builders/integration_core.py`
- `src/backend/dsl/yaml_loader.py`

## S49-S62 cumulative (14 sprints)

| Sprint | God-files fully closed | TDs closed |
|--------|------------------------|------------|
| S49-S61 | 43 | 6 |
| S62 | **+4** (admin_plugins, vocabulary, integration_core, yaml_loader) | — |
| **Total** | **47 god-files fully closed, 6 TDs closed** |

S62 alone: 2016 LOC → 17 well-organized files.

## S63+ candidates

Top remaining god-files after S62:
- `setup.py` 870 (S53 W3 — 25 helpers + orchestrator)
- `builders/base.py` 648 (S57 W1 — RouteBuilder MRO 59-level)
- `lifecycle/__init__.py` 585 (S59 W2 SKIPPED — sibling W82)
- `setup_infra.py` 534 (S60 W3 — but sibling may have re-created it)
- `loading.py` 496 (loader_v11)
- `routing.py` 496 (EIP)
- `marshal.py` 494 (EIP)
- `external_database.py` 492

S62 закрыт. Total commits: 5 (4 working + 1 closure).
