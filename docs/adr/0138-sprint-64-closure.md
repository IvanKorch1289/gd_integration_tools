# ADR-0138 — Sprint 64 closure: 4 god-file decomp (graphql, repositories, database, rag_service) (4+1 commits, 5/5 substantive)

* Статус: Accepted (Sprint 64 W5, 2026-06-10)
* Связано с: f971d4fc (W1 fixup), af55db75 (W2), 430b2ba2 (W3), cec49493 (W4), this ADR (W5)
* Контекст: PLAN.md V22 final, S49-S63 pattern continuation

## Контекст

Sprint 64 закрыл 4 god-file:
- graphql/schema.py 492 LOC (8 Pydantic types + Query 11 methods + Mutation 12 methods + Subscription 3 methods + 5 helpers → types + query + mutation + subscription + helpers)
- repositories/base.py 491 LOC (AbstractRepository 9 methods + SQLAlchemyRepository 11 methods + get_repository_for_model → base + sqlalchemy + factory)
- database.py 489 LOC (DatabaseBundle + DatabaseInitializer 13 methods + ExternalDatabaseRegistry 7 methods + 4 funcs → bundle + initializer + registry + accessors)
- rag_service.py 478 LOC (RAGService 14 methods + RAGCitation → 4 mixins + 1 core + state.py)

## Решения

1. **Resolvers + types + helpers split (graphql/schema.py, S64 W1)** — Strawberry GraphQL. 6 files: types(8 Pydantic) + query + mutation + subscription + helpers(5 funcs). **Required fixup**: orphan `@strawberry.type` in helpers.py + helper imports in resolver files.

2. **ABC + impl + factory split (repositories/base.py, S64 W2)** — Standard pattern (S55 W1 cert_store, S56 W3 s3_pool). 3 files: base(AbstractRepository ABC) + sqlalchemy(SQLAlchemyRepository concrete) + factory(get_repository_for_model).

3. **3 classes + 4 funcs split (database.py, S64 W3)** — Per-concern split: bundle + initializer + registry + accessors. DatabaseInitializer 13 methods kept as single class (manageable size).

4. **4-mixin MRO with state.py (rag_service.py, S64 W4)** — 14 methods split into Ingest(5) + Search(1) + Augment(3) + Collection(4) + 1 core. MRO 6-level. RAGCitation data class in state.py.

## Изменения

| File | Before | After | Decomposition |
|------|--------|-------|----------------|
| graphql/schema.py | 492 | 0 (deleted) | 8 types + 3 resolvers + 5 helpers → types + query + mutation + subscription + helpers |
| repositories/base.py | 491 | 0 (deleted) | AbstractRepo + SQLAlchemyRepo + helper → base + sqlalchemy + factory |
| database.py | 489 | 0 (deleted) | 3 classes + 4 funcs → bundle + initializer + registry + accessors |
| rag_service.py | 478 | 0 (deleted) | RAGService 14 methods → 4 mixins + 1 core + state.py (MRO 6-level) |
| **Total** | **1950** | **0 (replaced)** | **24 files created** |

## Quality gates (S64 scope)

- **mypy**: S64 changes clean
- **ruff**: clean for S64 changes
- Sibling WIP outstanding: 1700+ mypy errors

## Patterns re-used from S49-S63

- **MRO composition** (S49-S63 all MRO waves)
- **Per-concern file split** (S57 W4 sink_publish, S58 W3 format_converters, S59 W1 banking_processors, S60 W2 cdc, S62 W2 vocabulary, S63 W1 loading)
- **ABC + impl + factory split** (S55 W1 cert_store, S56 W3 s3_pool, S64 W2 repositories)
- **`@dataclass(slots=True)` conflict with mixin `__slots__ = ()`** (S57 W1 lesson)
- **`from __future__` deduplication + move to top** (S57 W1, S58 W2 lessons)
- **Use `.venv/bin/python` explicitly for AST parsing** (S61 W1 lesson)

## Lessons learned (для sprint-execution skill)

1. **Strawberry `@strawberry.type` orphan in helpers file** (S64 W1 NEW): when extracting top-level helpers from a Strawberry GraphQL schema, the `extract_func` logic must not pick up `@strawberry.type` decorator from the PREVIOUS class. Add explicit check: if function has no decorator, don't add one.

2. **Cross-imports for resolver files in split GraphQL schema** (S64 W1 NEW): Query/Mutation/Subscription resolvers call top-level helper funcs (`_dispatch_action`, `_schema_to_order`). When helpers move to separate file, each resolver file needs `from .helpers import ...`.

3. **`subprocess.run(['.venv/bin/python', '-c', ...])` requires `import json` in the inner code** (S64 W4 lesson): when running a string with subprocess, the inner code is in a fresh namespace — don't assume imports from outer script are available.

4. **JSON-encoded class info extraction for files with 3.12+ syntax** (S64 W2 lesson): when source has generic class syntax `class AbstractRepository[T]:`, can't parse with /bin/python. Use subprocess with .venv/bin/python and JSON-encode the result for transfer.

## Files Modified

### Created (24 new files)
- `src/backend/entrypoints/graphql/schema/{__init__,types,query,mutation,subscription,helpers}.py` (6 files)
- `src/backend/infrastructure/repositories/base/{__init__,base,sqlalchemy,factory}.py` (4 files)
- `src/backend/infrastructure/database/database/{__init__,bundle,initializer,registry,accessors}.py` (5 files)
- `src/backend/services/ai/rag_service/{__init__,ingest_mixin,search_mixin,augment_mixin,collection_mixin,state}.py` (6 files)

### Deleted (4 god-files)
- `src/backend/entrypoints/graphql/schema.py`
- `src/backend/infrastructure/repositories/base.py`
- `src/backend/infrastructure/database/database.py`
- `src/backend/services/ai/rag_service.py`

## S49-S64 cumulative (16 sprints)

| Sprint | God-files fully closed | TDs closed |
|--------|------------------------|------------|
| S49-S63 | 51 | 6 |
| S64 | **+4** (graphql, repositories, database, rag_service) | — |
| **Total** | **55 god-files fully closed, 6 TDs closed** |

S64 alone: 1950 LOC → 24 well-organized files.

## S65+ candidates

Top remaining god-files:
- `setup.py` 854 (S53 W3 — 25 helpers + orchestrator)
- `builders/base.py` 646 (S57 W1 — RouteBuilder MRO 59-level)
- `lifecycle/__init__.py` 585 (S82 sibling)
- `setup_infra.py` 530 (S60 W3 — sibling re-created)
- `airflow_operators.py` 485
- `llm_structured.py` 485
- `config/base.py` 485
- `grpc_server.py` 480
- `components.py` 479

S64 закрыт. Total commits: 5 (4 working + 1 closure).
