# Findings — Re-audit (post-S109, 2026-06-13)

> Verified against master HEAD `4dc2a7ac` (S109 closure).
> 30 audit points. Status legend:
> - ✅ **DONE** — fully resolved
> - ⚠️ **PARTIAL** — partially addressed, residual work
> - ❌ **ABSENT** — not started
> - 🔄 **REGRESSED** — was working, now broken
> - ➖ **NO LONGER RELEVANT** — outdated

---

## 1. JupyterHub integration & execution notebooks

**Status:** ✅ DONE
**Evidence (current code):** 3 backends via DI provider
`src/backend/core/di/providers/jupyter.py` →
`src/backend/infrastructure/clients/external/jupyter_hub.py`;
3 DSL processors
(`notebook_dsl.py`, `notebook_execute.py`, `notebook_export.py`);
notebook indexer in `src/backend/services/notebooks/indexer.py`;
mongo repo `infrastructure/repositories/notebooks_mongo.py`;
models `core/models/notebooks.py`;
endpoints `entrypoints/api/v1/endpoints/notebooks.py`.
**Impact:** High — notebooks are first-class DSL citizens.
**Residual:** None observed.

## 2. Layer independence

**Status:** 🔄 **REGRESSED (significant)**
**Evidence (current linter output):**
- `tools/check_layers.py --root extensions` — **36 NEW violations** (active).
  Top targets: `services.plugins.manifest_v11` (5 calls),
  `services.core.base` (4), `infrastructure.repositories.base` (4),
  `infrastructure.database.session_manager` (3),
  `infrastructure.repositories.orderkinds` (1, but S106 W3
  `moved to core/domain/models/orderkinds.py` — linter NOT updated
  to recognize the move).
- `tools/check_layers.py --root src/backend/services` — **15 NEW violations**
  (active).
- `tools/check_layers.py --root src/backend/core` — **200 stale allowlist
  entries** (need refresh post-TD-001).
**Last layer-policy work:** S106 W1-W3 (Risk A models to
`core/domain/models/`). **S107-S109 (TD-residual + TD-004)
completely ignored layer policy** — no linter work since 14 sprints.
**Priority:** P0.
**Recommendation:** Sprint 1 — refresh allowlist + migrate
extensions to canonical locations (D5 B2/B3 + ext→services).

## 3. Performance: connection pools, batching, parallelism

**Status:** ✅ DONE
**Evidence:** `infrastructure/persistence/{mssql,mysql,db2}` (S104 W3);
`core/resilience/circuit_breaker.py` (S100); `infrastructure/execution/dask_backend.py`;
smart session manager `infrastructure/database/session_manager.py`;
connection pools `infrastructure/clients/storage/s3_pool/client.py` (493 LOC).
**Residual:** DSN driver availability check (optional deps) — runtime risk.
**Priority:** P3.

## 4. Policies & custom agent limits

**Status:** ✅ DONE
**Evidence:** 4-mixin AIPolicyEnforcer (`core/ai/policy/enforcer/`);
`core/ai/workspace_manager.py` (S108 W3 migrated to canonical facade);
`ai_policies/` directory.
**Residual:** DSL exposure limited — see DSL coverage.

## 5. Global DI for future extensions

**Status:** ✅ DONE
**Evidence:** `core/di/container.py`; 8 providers
(`ai.py`, `auth.py`, `cache.py`, `db.py`, `http.py`, `jupyter.py`,
`workflow.py`, `__init__.py`).
**Residual:** None observed.

## 6. No duplicate libraries / duplicate code

**Status:** ✅ MOSTLY DONE
**Evidence:** D5 B1 (S106 W1) moved 7 Risk A models to canonical
location with shims + `DeprecationWarning` — pattern proven.
S107 W3 fully split `core/audit/facade.py` (394 LOC god-module)
→ `core/audit/facade/{_base,ai,authorization,banking,capability,secrets,waf}.py`
(7 modules per S106 W2 helper taxonomy). S109 closed TD-004 audit
migration (73 → 29 callsites).
**Residual:** 5 D5 B2/B3 model files (orders, orderkinds, files,
workflow_instance, workflow_event) still in
`infrastructure/database/models/`. 29 audit callsites remaining
(mixin internals — already dual-emit at S106 W5, no further
migration needed).

## 7. Dead/smelly code, where to replace with library

**Status:** ✅ MOSTLY DONE
**Evidence:** S107 W3 split `core/audit/facade.py` god-module.
Largest files now: lifespan.py (718), admin_plugins.py (514),
ops/health.py (589), outbox.py (527), grpc_server.py (483),
agent_dsl/infra.py (473), sql_alchemy.py (470) — all
**decomposed** (no >800 LOC god files per current scan).
**Residual:** None critical.

## 8. Directory organization by domain

**Status:** ✅ MOSTLY DONE
**Evidence:** `src/backend/core/` 40+ sub-packages — large but
functional. Frontend (Streamlit 119 files) organized.
**Residual:** `src/frontend/streamlit_app/` 119 files — minor
internal structure improvement possible.

## 9. Scheduling / workflow / DSL / runtime / restart / HITL / sub-workflow

**Status:** ✅ DONE
**Evidence:** `cron_schedule` (S103 W2) +
`temporal_scheduler_backend` (S105 W3) + `sub_workflow` DSL
method (`integration_core/workflow_mixin.py`) +
HITL tutorial `06_hitl_workflow.md` +
`saga_lra.py` for distributed transactions.
**Residual:** None observed.

## 10. Agent workflow, prompt cache, orchestration, resource isolation, RAG/RLM

**Status:** ✅ DONE
**Evidence:** 3-tier RAG cache (Redis exact + Qdrant semantic +
retrieval) — `infrastructure/cache/rag/`,
`clients/storage/vector_store.py`; LangMem
(`core/ai/langmem_models`); prompt versioning
(`services/ai/prompt_registry`); AI tool registry
(`services/ai/tools/registry.py` with `from_service` /
`from_plugin_file` / `@agent_tool`).
**Residual:** DSL exposure of AI operations — `ai_tool_dispatch`
+ `ai_invoke` present but limited.

## 11. Frontend: lightness & documentation

**Status:** ⚠️ PARTIAL
**Evidence:** 119 Streamlit pages, `06_streamlit_dashboard.md`
tutorial, 813 frontend files. S78 W3 Streamlit config security
gate exists.
**Residual:** No per-page feature split.
**Priority:** P3.

## 12. Documentation / docstrings / cookbooks / checks

**Status:** ✅ DONE
**Evidence:** 147 ADRs; 6+ cookbooks; 18+ tutorials; 5+ how-to;
docstring gate covers 8 dirs (extended S101 W3);
S100 W3 ratchet added 10 NEW docstrings
(docs_indexer.py, blueprint_loader.py, content_mixin.py).
Baseline 1641 allowlist entries, 0 NEW violations.
**Residual:** Slow ratchet burn-down (1641 entries).
**Priority:** P3.

## 13. DSL + directory scanning overhead

**Status:** ⚠️ PARTIAL
**Evidence:** Hot-reload via `watchfiles.awatch` (Rust);
YAML loader in `dsl/yaml_loader/`.
**Residual:** Not measured in current audit.
**Priority:** P3.

## 14. CDC и запуск без Kafka

**Status:** ✅ DONE
**Evidence:** 5 backends via `get_cdc_source()`
(`core/cdc/registry.py`): poll, listen_notify, debezium, adapter,
fake. CDC source processors
(`dsl/engine/processors/cdc_capture.py`).
**Residual:** None observed.

## 15. Webhooks / WebSockets / SOAP / XML / REST / GraphQL / gRPC / file passing

**Status:** ✅ DONE (R3 from previous re-audit RESOLVED)
**Evidence:** `check_protocol_coverage.py` — **OK**.
  - `entrypoints/_action_bridge.py` — exists ✅
  - `entrypoints/websocket/ws_handler.py` — exists ✅
  - `entrypoints/webhook/handler.py` — exists ✅ (S107+)
  - `entrypoints/express/router.py` — exists ✅
  - `entrypoints/sse/handler.py` — exists ✅ (S107+)
**Residual:** None.

## 16. Transform/aggregate/split/enrich/multicast/retry/backoff/CB DSL

**Status:** ✅ DONE
**Evidence:** `camel_eip.py` + `dsl/builders/eip/messengers.py`
(397 LOC) + `control_flow.py` (416 LOC) +
`core/resilience/circuit_breaker.py`.

## 17. Middleware + DSL

**Status:** ✅ DONE
**Evidence:** 28+ builtin middleware in
`src/backend/entrypoints/middlewares/` (12+ files visible);
4 layers (auth, rate-limit, correlation, audit);
cookbook 04.

## 18. External DB connectors + queries + DML DSL

**Status:** ✅ DONE
**Evidence:** S104 W3 — MSSQL/MySQL/DB2 DSN;
S95 W1 — `db_insert/db_upsert/db_delete` DML DSL;
DuckDB, JDBC, ClickHouse, Mongo processors.
**Residual:** Driver availability check.

## 19. Config / stage / internal settings / constants / certs / shared abstractions

**Status:** ✅ DONE
**Evidence:** `core/config/` with `services/{cache,queue,storage,mail}.py`,
`core/enums/`, `config_profiles/`, vault, `core/secrets_sources.py`,
`core/config/features/` (Sprint 24-27 flags).

## 20. RPA / SSH / files / archive / OCR / S3 / disk / browser

**Status:** ⚠️ MOSTLY DONE
**Evidence:** `ssh_exec` DSL method (`dsl/builders/notify.py`);
`s3_get/s3_put/sftp_get/sftp_put` (S104 W1);
`zip_archive.py`, `rpa_browser.py`, `desktop_pyautogui.py`,
`scan_file.py` processors.
**Residual:** **`s3_delete`, `s3_list` STILL missing** (D17 from
previous re-audit — verified via `rg "def s3_(delete|list)"` = 0 matches).
**Priority:** P3.

## 21. Cache + SSE + DSL

**Status:** ✅ DONE
**Evidence:** Cache facade (4 backends — Redis, KeyDB, Memcached, Memory);
SSE `from_sse_multi` DSL method (S96 W4) + `from_sse`;
`entrypoints/sse/handler.py` (verified S107+).

## 22. Architecture changes after S93-S109 work (S106 W2 → S109)

**Status:** ✅ MAJOR PROGRESS
**Evidence:** 17 sprints (S93-S109), 124+ atomic commits,
525+ NEW tests, 18 ADRs (0175-0195), score 9.4 → 9.8.
Major moves S107-S109:
- **S107 W3**: `core/audit/facade.py` (394 LOC god-module) →
  `core/audit/facade/` package (7 modules)
- **S107 W5**: Real `NatsSource` + `MongoSource` runtime (TD-010
  followup)
- **S108 W1**: Dependabot esbuild 0.28.1 (2 high CVEs closed)
- **S108 W3**: `workspace_manager.py` → canonical `emit_ai_workspace`
- **S108 W4**: AIToolDispatch real LLM-wiring + 2 e2e tests
- **S109 W1-W4**: TD-004 audit migration (73 → 29 callsites);
  WAF + activity capability dual-emit to canonical facade;
  ai_banking migrated to `emit_banking_audit`; method renames
  for mixin internals.

## 23. Items fully closed (S107-S109)

- S107 W3: `core/audit/facade.py` god-module split
- S107 W5: Real `NatsSource` + `MongoSource` runtime
- S108 W1: Dependabot esbuild 0.28.1 (2 high CVEs)
- S108 W3: TD-004 AI workspace domain migration
- S108 W4: AIToolDispatch e2e tests
- S109 W1: WAF + activity capability dual-emit
- S109 W2: ai_banking domain migration
- S109 W3-W4: 5 files method rename (22 callsites)
- TD-004: 73 → 29 callsites (-60%)

## 24. Items partially closed (or regressed)

- **R1 (regressed)**: Layer policy NOT enforced in S107-S109 — 36
  NEW ext violations + 15 NEW services violations + 200 stale
  core allowlist entries. **This is the most critical regression
  in S107-S109**.
- **R2 (stale)**: D5 B2/B3 model files (orders, orderkinds, files,
  workflow_instance, workflow_event) still in
  `infrastructure/database/models/` — extensions keep importing
  from there (linter violation).
- **R3 (D17 still missing)**: `s3_delete` + `s3_list` DSL methods
  not added (gap since DEEP-RESEARCH).

## 25. Architecture regressions (S107-S109 introduced)

- **Layer policy drift**: 51 NEW active layer violations (36 ext
  + 15 services) introduced in S107-S109. Root cause:
  extensions moved/migrated without updating linter allowlist,
  + `infrastructure.repositories.orderkinds` was moved to
  `core/domain/models/orderkinds.py` in S106 W3 but extensions
  still import from old location.
- **Audit facade canonical split** (S107 W3) = positive refactor
  but **created TD-008 split** (already verified S108 W2, no
  regressions).

## 26. New hotspots after S93-S109

| Hotspot | File | LOC | Notes |
|---------|------|-----|-------|
| `core/audit/facade/` | 7 modules | ~450 | S107 W3 split — clean |
| DSL `transport/sources.py` | sources mixin | growing | from_nats/from_mongo added |
| `lifespan.py` | 718 LOC | largest single | decomposition candidate |

## 27. Hidden complexity

- `dsl/builders/transport/sources.py` — 25+ source methods in one
  file (S107 added from_nats, from_mongo, from_nats_js).
  Candidate for split into per-protocol modules.
- `core/audit/facade/` (7 modules) — clean post-S107 W3 split,
  no further action.
- `lifespan.py` (718 LOC) — multi-phase startup logic, could
  be split into per-phase handlers.

## 28. Extension blockers

- Layer policy drift (R1) — extensions can't safely migrate to
  `core.domain.models` for Risk B/C models until linter refreshed.
- Audit dual architecture — extensions use `self._audit: Callable`
  (legacy) or `get_unified_audit_service()` (new). Both paths
  supported, no migration blocker.

## 29. Extension API instability

- ✅ `extensions/core_entities/users/domain/models.py` re-exports
  from `core.domain.models.users` (S106 W1, clean).
- ❌ `extensions/core_entities/orders`, `orderkinds`, `files`
  still import from `infrastructure.database.models.*` —
  linter violations.

## 30. Candidates for split/merge/delete

| File | Action | Reason |
|------|--------|--------|
| `dsl/builders/transport/sources.py` | REVIEW | 25+ source methods, candidate per-protocol split |
| `lifespan.py` (718 LOC) | REVIEW | Multi-phase startup, candidate per-phase split |
| `infrastructure/database/models/{orders,orderkinds,files,workflow_instance,workflow_event}.py` | MOVE | D5 B2/B3 backlog — extensions still reference |

---

## Summary by priority

| Priority | Items | Sprint |
|----------|-------|--------|
| **P0** | Layer policy refresh (51 NEW violations + 200 stale allowlist) | **Sprint 1** |
| **P1** | D5 B2/B3 (move 5 model files to `core/domain/models/`) — unblocks extensions | **Sprint 1** |
| **P2** | `s3_delete` + `s3_list` DSL methods (D17) | **Sprint 2** |
| **P3** | Streamlit feature-grouping, slow ratchet, control_flow.py review, lifespan.py decomposition | continuous |
| **Continuous** | TD-004 (29 remaining — mixin internals, soft close), TD-012 docstring ratchet |
