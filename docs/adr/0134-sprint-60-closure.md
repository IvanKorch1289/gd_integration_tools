# ADR-0134 — Sprint 60 closure: 4 god-file decomp (jupyter, cdc, setup_infra, authorization_gateway) (4+1 commits, 5/5 substantive)

* Статус: Accepted (Sprint 60 W5, 2026-06-10)
* Связано с: c5c6eb42 (W1), b0107821 (W2), 7805550a (W3), e16245ab (W4), this ADR (W5)
* Контекст: PLAN.md V22 final, S49-S59 pattern continuation

## Контекст

Sprint 60 закрыл 4 god-file:
- jupyter/execution_service.py 571 LOC (NotebookExecutionService 10 methods → 3 mixins + 2 core + 2 helper files)
- cdc.py 538 LOC (7 classes + 1 helper → 3 file split)
- setup_infra.py 534 LOC (13 top-level funcs → 4 file split)
- authorization_gateway.py 530 LOC (AuthorizationGateway 9 methods → 4 mixins + 5 core + state.py)

## Решения

1. **MRO + helper files (jupyter/execution_service.py, S60 W1)** — 10 methods + 2 helper classes (errors + backend). Mixins: Core(1) + IO(3) + JupyterBackend(4) + 2 core. Errors + backend kept as separate files.

2. **Per-concern file split (cdc.py, S60 W2)** — 7 classes split into events(2) + strategies(4) + client(1+1). Each strategy file imports from events; client imports from both.

3. **Per-concern top-level funcs split (setup_infra.py, S60 W3)** — 13 funcs split into health(2) + pools(5) + workflow_audit(2) + lifecycle(4). Cross-imports for orchestrators.

4. **Per-external-service MRO (authorization_gateway.py, S60 W4)** — 9 methods split into 4 mixins (1 per external service: Casbin, OPA, Permission) + 1 AuditMixin + 5 core. State.py for 2 small data classes.

## Изменения

| File | Before | After | Decomposition |
|------|--------|-------|----------------|
| jupyter/execution_service.py | 571 | 0 (deleted) | 10 methods + 2 helpers → 3 mixins + 2 core + errors.py + backend.py (MRO 5-level) |
| cdc.py | 538 | 0 (deleted) | 7 classes + 1 helper → events(2) + strategies(4) + client(1+1) |
| setup_infra.py | 534 | 0 (deleted) | 13 funcs → health(2) + pools(5) + workflow_audit(2) + lifecycle(4) |
| authorization_gateway.py | 530 | 0 (deleted) | 9 methods + 2 classes → 4 mixins + 5 core + state.py (MRO 6-level) |
| **Total** | **2173** | **0 (replaced)** | **20 files created** |

## Quality gates (S60 scope)

- **mypy**: S60 changes clean
- **ruff**: clean for S60 changes
- Sibling WIP outstanding: 1700+ mypy errors (Redis WIP has broken `redis_client` import — sibling will fix in their commit)

## Patterns re-used from S49-S59

- **MRO composition** (S49-S59 all MRO waves)
- **Per-concern file split** (S57 W4 sink_publish, S58 W3 format_converters, S59 W1 banking_processors)
- **Helper files for small classes** (errors.py + backend.py pattern from S58 W2 saga_lra_processor)
- **Cross-imports for mixin/subclass structures** (S55 W1 cert_store, S59 W1 banking_processors)
- **`from __future__` deduplication + move to top** (S57 W1, S58 W2 lessons)

## Lessons learned (для sprint-execution skill)

1. **Per-external-service MRO pattern** (S60 W4 NEW): when a god-class orchestrates multiple external services (Casbin/OPA/Permission), use one mixin per service + a thin core. Makes it easy to add/remove service integrations.

2. **Top-level funcs file split pattern** (S60 W3 NEW): for files with only top-level funcs (no class), split per concern. Orchestrator funcs (e.g., lifecycle.py) cross-import helper funcs from other files.

3. **Sibling WIP can break adjacent files** (S60 W3 lesson): sibling's incomplete Redis refactor left broken `from redis import redis_client` import in setup_infra/health.py. Don't try to fix sibling WIP in your own commit — let them handle it.

## Files Modified

### Created (20 new files)
- `src/backend/services/jupyter/execution_service/{__init__,core_mixin,io_mixin,jupyter_mixin,errors,backend}.py` (6 files)
- `src/backend/infrastructure/clients/external/cdc/{__init__,events,strategies,client}.py` (4 files)
- `src/backend/plugins/composition/setup_infra/{__init__,health,pools,workflow_audit,lifecycle}.py` (5 files)
- `src/backend/core/security/authorization_gateway/{__init__,audit_mixin,casbin_mixin,opa_mixin,permission_mixin,state}.py` (6 files)

### Deleted (4 god-files)
- `src/backend/services/jupyter/execution_service.py`
- `src/backend/infrastructure/clients/external/cdc.py`
- `src/backend/plugins/composition/setup_infra.py`
- `src/backend/core/security/authorization_gateway.py`

## S49-S60 cumulative (12 sprints)

| Sprint | God-files fully closed | TDs closed |
|--------|------------------------|------------|
| S49-S59 | 35 | 6 |
| S60 | **+4** (jupyter, cdc, setup_infra, authorization_gateway) | — |
| **Total** | **39 god-files fully closed, 6 TDs closed** |

S60 alone: 2173 LOC → 20 well-organized files.

## S61+ candidates

| Task | Effort | Notes |
|------|--------|-------|
| services/core/base.py 526 | 1 wave | base class |
| enrichment.py 523 | 1 wave | enrichment proc |
| executor.py 514 | 1 wave | workflow executor |
| http.py 514 | 1 wave | transport http |
| TD-006 / TD-005 / TD-008 | analysis | low risk |
| Sibling WIP push | — | 1700+ mypy errors |

S60 закрыт. Total commits: 5 (4 working + 1 closure).
