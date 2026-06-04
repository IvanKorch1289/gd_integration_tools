# Dead Code & TODO/FIXME Audit Report

**Sprint**: S40 W6
**Date**: 2026-06-04
**Scope**: `src/backend/` (production source, tests excluded)
**Tools**: `ruff` (F401, F841), `grep`, `python -c` (AST)
**Status**: ANALYSIS ONLY — no source code modified, no commit performed

---

## 1. Executive Summary

| Metric                              | Count  | Target | Status |
|-------------------------------------|-------:|-------:|--------|
| Total Python files in `src/backend` |   1478 |    —   | —      |
| Non-init modules                    |   1265 |    —   | —      |
| Total LOC (src/backend)             | 231109 |    —   | —      |
| TODO/FIXME/XXX/HACK markers         |     17 |     0  | FAIL   |
| Unused imports (ruff F401)          |      0 |     0  | PASS   |
| Unused variables (ruff F841)        |      0 |     0  | PASS   |
| Zero-import non-init modules        |    292 |   low  | WARN   |
| Largest dead-candidate cluster      | ~48.7k |    —   | —      |

**Headline findings**

* Source is linter-clean: zero F401 (unused imports) and zero F841 (unused
  variables) per `ruff` — confirms ongoing `make lint` discipline.
* 17 TODO/FIXME markers remain, concentrated in `sms.py` adapter, middleware
  registry, and admin sso. Sprint-tagged TODOs are legitimate; a focused
  resolve is feasible.
* 292 non-init modules have zero internal imports (~23% of all modules).
  Many are entrypoints, Protocols, and registry backends registered via
  decorators or `app_factory` — likely *not* dead, but the cluster warrants
  a vulture/pyright reachability pass.

---

## 2. TODO / FIXME / XXX / HACK Audit

Raw `grep -rE 'TODO|FIXME|XXX|HACK' src/backend/ --include='*.py' | wc -l`
returns 26 lines; after excluding false positives (`XXX`/`XX` appearing in
PII format examples like `XXX-XXX-XXX YY` or `\uXXXX`), **17 real markers**
remain across 9 files.

### 2.1. Per-file breakdown

| File                                                          | Count | Notes                                                          |
|---------------------------------------------------------------|------:|----------------------------------------------------------------|
| `services/admin/sso.py`                                       |     2 | S20: `require_sso_auth` decorator for admin endpoints          |
| `infrastructure/notifications/adapters/sms.py`                |     5 | Scaffolding — verify MTS/МегаФон endpoints and payload formats  |
| `infrastructure/workflow/executor.py`                         |     1 | B1-phase-2: full Exchange + ExecutionContext wiring            |
| `dsl/cli/generate.py`                                         |     1 | `Implement {name}` placeholder in template generator           |
| `dsl/engine/processors/llm_structured.py`                     |     1 | Sprint 9: `OutboundHttpClient` litellm-hook                    |
| `dsl/engine/processors/express/_common.py`                    |     1 | Wave 4.2: callback receiver for express processor              |
| `dsl/workflow/compiler/step_compilers.py`                     |     1 | S24 W3: LangGraph Checkpointer integration                     |
| `core/middleware/registry.py` + `core/middleware/__init__.py` |     3 | S18: full chain builder per ADR-A-01                            |
| `core/config/features/__init__.py`                            |     1 | flag-deprecation follow-up step                                |

### 2.2. Recommendations

* **Cluster A — Sprint-tagged (KEEP)**: S18, S20, S24 W3, Sprint 9,
  B1-phase-2, Wave 4.2. Tracked work items with sprint assignment;
  converting them to `gh:`/Jira references is recommended but not blocking.
* **Cluster B — Scaffolding (RESOLVE)**: 5 TODOs in
  `notifications/adapters/sms.py` flag unverified third-party endpoints.
  Either confirm and remove, or raise `NotImplementedError` at runtime so
  callers fail loud instead of silently hitting a wrong URL.
* **Cluster C — Placeholder (FIX)**: 1 TODO in `dsl/cli/generate.py:304`
  is a template generator placeholder; implement or guard with
  `NotImplementedError`.

---

## 3. Unused Imports (ruff F401)

```
.venv/bin/python -m ruff check --select F401 src/backend/
→ All checks passed!
```

**Count: 0**. One pre-existing `# noqa` directive in
`src/backend/core/utils/task_registry.py:95` is malformed (expected
comma-separated list); fix opportunistically.

## 4. Unused Variables (ruff F841)

```
.venv/bin/python -m ruff check --select F841 src/backend/
→ All checks passed!
```

**Count: 0**. No unused local variables detected.

---

## 5. Zero-Import Module Cluster

AST-based analysis of `from src.backend.* import …` references (cross-
module imports only — does not count type-only re-exports or runtime
registration via decorators / `app_factory` / `PluginLoader`).

| Bucket                                            | Count  |
|---------------------------------------------------|-------:|
| Total non-init modules in `src/backend/`          |   1265 |
| Imported by at least one other module             |    973 |
| **Zero imports (candidate cluster)**              | **292**|
| Approx. lines in zero-import cluster              | ~48.7k |

### 5.1. Top 20 deletion candidates (by line count)

| LOC  | Module                                                                          |
|-----:|---------------------------------------------------------------------------------|
|  598 | `infrastructure.database.migrations.versions.2025_03_10_1637-20036813ff7c_`     |
|  590 | `dsl.builders.sources_mixin`                                                    |
|  587 | `dsl.processors.saga_lra_processor`                                             |
|  574 | `dsl.codec.format_converters`                                                   |
|  530 | `dsl.engine.processors.enrichment`                                              |
|  513 | `entrypoints.api.v1.endpoints.admin_plugins`                                   |
|  492 | `services.io.external_database`                                                 |
|  472 | `dsl.processors.idp_pipeline_processor`                                         |
|  464 | `core.resilience.backpressure`                                                  |
|  460 | `services.ai.semantic_cache`                                                    |
|  455 | `entrypoints.grpc.grpc_server`                                                  |
|  446 | `dsl.engine.processors.rpa_browser`                                             |
|  445 | `infrastructure.secrets.vault_client`                                           |
|  426 | `dsl.workflow.bpmn_importer`                                                    |
|  407 | `services.ops.health`                                                           |
|  403 | `workflows.worker`                                                              |
|  396 | `ops.health`                                                                    |
|  371 | `core.actions.proto_adapter`                                                    |
|  361 | `infrastructure.workflow.builder`                                               |
|  360 | `infrastructure.clients.connection_reuse`                                       |

### 5.2. Caveats — many "zero-import" modules are NOT dead

* **Entrypoints** (`entrypoints/api/v1/endpoints/*`, `entrypoints/grpc/*`,
  `entrypoints/mcp/*`, `entrypoints/websocket/*`, `entrypoints/email/*`)
  wired via `app_factory` / `include_router`, not direct import.
* **Workers / health probes** (`workflows/worker.py`, `ops/health.py`,
  `services/ops/health.py`, `entrypoints/middlewares/*`) registered by
  `add_middleware()` / `worker_main()` startup hooks.
* **Protocols / interfaces** (`core/interfaces/*`, `core/protocols.py`,
  `core/auth/protocols.py`) referenced via structural subtyping or
  `isinstance` checks.
* **Migrations** (`infrastructure/database/migrations/versions/*`) applied
  by Alembic.
* **Vault / secrets** (`infrastructure/secrets/*`) instantiated via DI from
  `core/config/settings.py`.
* **CLI commands** (`dsl/cli/*`) discovered via `click`/`typer` decorators.

### 5.3. Recommended next step

Build a vulture/pyright reachability pass combining: (1) import-graph
(this audit); (2) decorator / entry-point registration (scan for
`@app.get`, `@router.post`, `@processor`, `@service_dsl`, `add_middleware`,
`include_router`); (3) `getattr` / `globals()` lookups. Output: a stricter
"definitely unreachable" list for S40 W7 cleanup.

---

## 6. Per-File Recommendations (priority order)

| Priority | File / Group                                            | Action                                                  |
|----------|---------------------------------------------------------|---------------------------------------------------------|
| P1       | `infrastructure/notifications/adapters/sms.py`          | Resolve 5 scaffolding TODOs (verify or hard-fail)       |
| P1       | `dsl/cli/generate.py:304`                               | Implement `Implement {name}` or raise NotImplementedError |
| P2       | `services/admin/sso.py` + `core/middleware/registry.py` | Link S18/S20 TODOs to Jira epics                        |
| P2       | `core/utils/task_registry.py:95`                        | Fix malformed `# noqa` directive                       |
| P3       | `infrastructure/workflow/executor.py`                   | B1-phase-2 Exchange wiring — track in plan              |
| P3       | `dsl/workflow/compiler/step_compilers.py:319`           | S24 W3 LangGraph Checkpointer — track in plan           |
| P4       | Zero-import cluster (292 modules)                       | Schedule focused vulture/pyright reachability audit     |

---

## 7. Verification Commands

```bash
# TODO/FIXME count (raw)
grep -rE 'TODO|FIXME|XXX|HACK' src/backend/ --include='*.py' | wc -l

# Real TODO/FIXME (excluding PII format examples)
grep -rEn 'TODO|FIXME|XXX|HACK' src/backend/ --include='*.py' \
  | grep -vE 'XXX-XX|XXXX|\bXXX\b' | grep -cE 'TODO|FIXME|XXX|HACK'

# Unused imports / variables
.venv/bin/python -m ruff check --select F401,F841 src/backend/
```

---

## 8. Audit Metadata

* Audit scripts (transient): `/tmp/audit_imports.py`, `/tmp/audit_dead.py`
* Tools: `ruff`, `python 3.14+` (AST), `grep` (GNU)
* Working dir: `/home/user/dev/gd_integration_tools`
* Files written: `docs/DEAD_CODE_AUDIT.md` (this file)
* Files modified: NONE
* Commits created: NONE (per task boundary)
