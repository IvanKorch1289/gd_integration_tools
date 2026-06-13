# Findings — DEEP-RESEARCH + New Audit (per-point)

> 30 audit points. Status legend:
> - ✅ **DONE** — fully resolved, evidence in current code
> - ⚠️ **PARTIAL** — partially addressed, residual work exists
> - ❌ **ABSENT** — not started
> - 🔄 **REGRESSED** — was working, now broken
> - ➖ **NO LONGER RELEVANT** — DEEP-RESEARCH claim outdated

---

## 1. JupyterHub integration & execution notebooks

**Status:** ✅ DONE
**Evidence:** 3 backends (Papermill/NbClient/E2B) + 3 DSL processors, `docs/cookbooks/03-e2b-jupyter-sandbox.md`
**Impact:** High — notebooks are first-class DSL citizens.
**Residual:** None observed.

## 2. Layer independence

**Status:** ⚠️ PARTIAL
**Evidence:**
- `check_layers.py` (core) — **9 NEW violations** (`core/audit/facade.py` → `services/audit/audit_service`; `core/cdc/registry.py` → `infrastructure/cdc/cdc_client_adapter`)
- `check_layers.py` (extensions) — **39 NEW violations** (D5 B2/B3 backlog + ext→services)
- Legacy violations: 186 in allowlist (S84 W1 facade solved, but core 9 newly introduced)
**Priority:** P0
**Recommendation:** Sprint 1 — fix 9 core violations; Sprint 1-2 — close D5 B2/B3.

## 3. Performance: connection pools, batching, parallelism

**Status:** ⚠️ PARTIAL
**Evidence:** `infrastructure/persistence/{mssql,mysql,db2}` (S104 W3), `core/resilience/circuit_breaker.py` (S100), `infrastructure/execution/dask_backend.py`, smart session manager
**Residual:** DSN driver availability check (pyodbc/aioodbc optional deps) — runtime risk.
**Priority:** P1
**Recommendation:** Sprint 2 — driver availability check + pool health cookbook.

## 4. Policies & custom agent limits

**Status:** ✅ DONE
**Evidence:** 4-mixin AIPolicyEnforcer (R4), `core/ai/workspace_manager.py` (S85 closure), `ai_policies/` directory
**Impact:** High.
**Residual:** DSL exposure limited — see DSL coverage.

## 5. Global DI for future extensions

**Status:** ✅ DONE
**Evidence:** `core/di/container.py`, `core/di/providers/{ai,http,jupyter,security,...}.py` (12+ subdirs)
**Impact:** High.
**Residual:** None observed.

## 6. No duplicate libraries / duplicate code

**Status:** ⚠️ PARTIAL
**Evidence:**
- D5 B1 (S106 W1) successfully moved 7 Risk A models to canonical location, shims with `DeprecationWarning` — pattern proven.
- 2 audit architectures (DI-callback vs service-locator) — S105 W2 chose soft-deprecation (Path B), not consolidation.
- 5 model files still in old location (D5 B2/B3 backlog).
- `core/audit/facade.py` (394 LOC) — could be split into `facade/<domain>.py` per S106 W2 helper taxonomy.
**Priority:** P1
**Recommendation:** Sprint 1 — D5 B2 (orderkinds, orders, files). Sprint 1-2 — wire `emit_capability_check` helper in capability gate mixin (17 callsites in 1 commit).

## 7. Dead/smelly code, where to replace with library

**Status:** ⚠️ PARTIAL
**Evidence:**
- `S58 W1 LESSON (HARD): libraries > custom` — VersioningService 800 LOC replaced by continuum (proven lesson, see USER memory).
- `core/audit/facade.py` grew 74 → 394 LOC after S106 W2 — borderline god-module.
- `src/backend/dsl/builders/control_flow.py` (416 LOC) — could be library?
**Priority:** P2
**Recommendation:** Sprint 3 — opportunistic split `core/audit/facade.py` into `facade/` subpackage.

## 8. Directory organization by domain

**Status:** ⚠️ PARTIAL
**Evidence:** Most layers clean. `src/backend/core/` has 40+ sub-packages — large but functional.
**Residual:** `src/frontend/streamlit_app/` 119 files, no internal structure visible.
**Priority:** P3
**Recommendation:** Sprint 3 — group streamlit pages by feature.

## 9. Scheduling / workflow / DSL / runtime / restart / HITL / sub-workflow

**Status:** ✅ DONE
**Evidence:** S103 W2 (`cron_schedule`) + S105 W3 (`TemporalSchedulerBackend`) + HITL tutorial `06_hitl_workflow.md`
**Residual:** No explicit `sub_workflow` DSL method visible in builder methods.
**Priority:** P2
**Recommendation:** Sprint 2 — add `sub_workflow` method.

## 10. Agent workflow, prompt cache, orchestration, resource isolation, RAG/RLM/token economy

**Status:** ✅ DONE (per DEEP-RESEARCH)
**Evidence:** 3-tier RAG cache (Redis exact + Qdrant semantic + retrieval), langmem, prompt versioning, workspace isolation
**Residual:** DSL exposure of AI operations limited.
**Priority:** P2
**Recommendation:** Sprint 2 — DSL `ai_invoke`, `ai_tool_dispatch` methods.

## 11. Frontend: lightness & documentation

**Status:** ⚠️ PARTIAL
**Evidence:** 119 Streamlit pages, `06_streamlit_dashboard.md` tutorial
**Residual:** S78 W3 Streamlit config security gate exists; no per-page doc/feature split.
**Priority:** P3
**Recommendation:** Sprint 3 — feature-grouping.

## 12. Documentation / docstrings / cookbooks / checks

**Status:** ✅ DONE
**Evidence:**
- 140 ADRs (S67-S105)
- 6 cookbooks, 18 tutorials, 5 how-to
- Docstring gate extended 3 → 8 dirs (S101 W3)
- Ratchet: 0 NEW violations, baseline 1636 stable
**Residual:** Slow ratchet burn-down (1636 entries).
**Priority:** P3
**Recommendation:** Continue incremental ratchet in each sprint W4.

## 13. DSL + directory scanning overhead

**Status:** ⚠️ PARTIAL
**Evidence:** Hot-reload on `watchfiles.awatch` (Rust), but `dsl/loaders/` and `dsl/yaml_loader/` may have own perf profile.
**Residual:** Not measured in current audit.
**Priority:** P3
**Recommendation:** Sprint 3 — perf profile if budget allows.

## 14. CDC и запуск без Kafka

**Status:** ✅ DONE
**Evidence:** 5 backends via `get_cdc_source()` (poll, listen_notify, debezium, adapter, fake) — `fake` для local dev.
**Residual:** None observed.

## 15. Webhooks / WebSockets / SOAP / XML / REST / GraphQL / gRPC / file passing

**Status:** ⚠️ PARTIAL
**Evidence:** 12 protocols advertised, 8 entrypoint bridges present.
**Residual:** **4 missing handlers** per `check_protocol_coverage.py`:
- `entrypoints/websocket/ws_handler.py`
- `entrypoints/webhook/handler.py`
- `entrypoints/express/router.py`
- `entrypoints/sse/handler.py`
**Priority:** P1
**Recommendation:** Sprint 2 — close all 4 missing handlers in 1 commit (small files, mechanical).

## 16. Transform/aggregate/split/enrich/multicast/retry/backoff/circuit breaker DSL

**Status:** ✅ DONE (per DEEP-RESEARCH 10/10 EIP)
**Evidence:** `camel_eip.py` + `eip/` subpackage + `control_flow.py`
**Residual:** None observed.

## 17. Middleware + DSL

**Status:** ✅ DONE
**Evidence:** 28 builtin middleware, 4 layers, `core/middleware/registry.py`, cookbook 04
**Residual:** None observed.

## 18. External DB connectors + queries + DML DSL

**Status:** ✅ DONE
**Evidence:** S104 W3 — MSSQL/MySQL/DB2 DSN support; S95 W1 — `db_insert/db_upsert/db_delete` DML DSL
**Residual:** Driver availability check (optional deps) — runtime risk.
**Priority:** P2
**Recommendation:** Sprint 2 — driver check + cookbook.

## 19. Config / stage / internal settings / constants / certs / shared abstractions

**Status:** ✅ DONE
**Evidence:** `core/config/` with `services/{cache,queue,storage,mail}.py`, `core/enums/`, `config_profiles/`, vault, `core/secrets_sources.py`
**Residual:** None observed.

## 20. RPA / SSH / files / archive / OCR / S3 / disk / browser

**Status:** ✅ DONE (most)
**Evidence:**
- S104 W1 — `s3_get/sftp_get/sftp_put`
- S85 closure — ssh_exec (asyncssh)
- archive, browser in DSL
**Residual:** `s3_delete`, `s3_list` missing. OCR not confirmed.
**Priority:** P2
**Recommendation:** Sprint 3 — add `s3_delete/s3_list` if no other priorities.

## 21. Cache + SSE + DSL

**Status:** ⚠️ PARTIAL
**Evidence:** Cache facade exists (4 backends); SSE `from_sse_multi` DSL method (S96 W4) + `from_sse`.
**Residual:** `entrypoints/sse/handler.py` missing per protocol_coverage.
**Priority:** P1
**Recommendation:** Sprint 2 — add SSE handler.

## 22. Architecture changes after previous work

**Status:** ✅ MOSTLY DONE
**Evidence:** S93-S106 (16 sprints) closed 322+ NEW tests, 12 ADRs, score 9.0 → 9.5. Major moves: D5 split-brain B1, LangGraph Checkpointer, audit facade canonical, stdlib logging migration complete, Temporal Scheduler real, DSN multi-DB support, RPA DSL, rate limit facade, CDC registry.
**Residual:** 9 NEW core linter violations from S103+ work (audit facade, cdc registry) — need to fix.

## 23. Items fully closed

- D19 DSN MSSQL/MySQL/DB2 (S104 W3)
- D14 Docstring gate extended (S101 W3)
- D21 RPA DSL S3/SFTP (S104 W1)
- D9 cron_schedule (S103 W2)
- D5 B1 (S106 W1)
- V2 P0 #6 TenantMixin 7/7 (S102 W3)
- V2 P0 #10 HTTP drain (S103 W4)
- LangGraph Checkpointer (S100 W1)
- Audit facade canonical (S103 W3) + Path A helpers (S106 W2)
- Stdlib logging migration (S93-S98, audited S100 W4)
- DSL db_crud (S95 W1)
- RouteBuilder fix (S97 W1 — CRITICAL)
- Middleware closure (S98 W1)
- Auth relocation (S96 W1)
- Telegram DSL (S97 W4)
- Rate limit facade (S104 W2)
- Temporal Scheduler real (S105 W3)

## 24. Items partially closed

- D5 B2/B3 (5 model files remaining: orders, orderkinds, files, workflow_instance, workflow_event) — 39 linter violations
- Audit migration (77 callsites, 2 architectures coexist) — Path B soft-deprecation, no callsite migration
- Protocol coverage (4 missing handlers)
- Pre-commit hook auto-wire (in S106 backlog, not done)
- Docstring ratchet (1636 baseline, slow burn-down)

## 25. Architecture regressions

- **9 NEW core linter violations** — S103 W3 audit facade + S101 W1 cdc registry introduced new `core → services/infra` imports
- **39 NEW extension linter violations** — D5 B2/B3 backlog

## 26. New hotspots after S93-S106 work

| Hotspot | File | LOC | Notes |
|---------|------|-----|-------|
| Audit facade | `core/audit/facade.py` | 394 | S103 W3 (74) + S106 W2 (320) — god-module candidate |
| D5 model shims | `infrastructure/database/models/{base,cert,dsl_snapshot,langmem_models,outbox,rule_engine,users}.py` | ~600 | Back-compat shims, hard delete S106 W5 |
| Temporal backend | `infrastructure/scheduler/temporal_scheduler_backend.py` | NEW | S105 W3 |
| Audit helper taxonomy | `core/audit/facade.py` (7 helpers) | NEW | S106 W2 |

## 27. Hidden complexity (multiple scenarios in one module)

- `core/audit/facade.py` (7 helper functions, 394 LOC) — multiple domain patterns in one file. Candidate for split into `facade/{authorization,waf,capability,secret_rotation,ai_workspace,safe,banking}.py`.
- `core/security/capabilities/gate/audit_mixin.py` (1 `_emit_audit` method, 17 callsites) — the single method handles 6 different kwarg shapes.
- `src/backend/dsl/builders/control_flow.py` (416 LOC) — likely multiple control-flow patterns.

## 28. Extension blockers

- D5 split-brain (39 violations) — extensions can't safely migrate to `core.domain.models` for Risk B/C models until B2/B3 done.
- Audit dual architecture (DI-callback vs service-locator) — extensions must use `self._audit: Callable` pattern (legacy) or `get_unified_audit_service()` (new).

## 29. Extension API instability

- `extensions/core_entities/users/domain/models.py` re-exports from `core.domain.models.users` (S106 W1, clean).
- `extensions/core_entities/orders`, `orderkinds`, `files` still import from `infrastructure.database.models.*` — **linter violations** = 39.

## 30. Candidates for split/merge/delete

| File | Action | Reason |
|------|--------|--------|
| `core/audit/facade.py` (394 LOC) | SPLIT | 7 helpers → `facade/<domain>.py` |
| `infrastructure/database/models/{base,cert,dsl_snapshot,langmem_models,outbox,rule_engine,users}.py` | DELETE (S106 W5) | Shims, hard delete end of sprint |
| `src/backend/dsl/builders/control_flow.py` (416 LOC) | REVIEW | Likely split |
| `src/backend/dsl/builders/agent_dsl/infra.py` (409 LOC) | REVIEW | Agent DSL, may be god-class |
| `src/backend/dsl/builders/eip/messengers.py` (397 LOC) | REVIEW | EIP messenger, may be split |
| `src/backend/dsl/builders/transport/sinks.py` (377 LOC) | REVIEW | Transport sinks, may be split |
| `src/backend/dsl/builders/infrastructure_dsl.py` (383 LOC) | REVIEW | Infrastructure DSL, multi-domain |
| `src/frontend/streamlit_app/` (119 files) | ORGANIZE | Group by feature |

---

## Summary by priority

| Priority | Items |
|----------|-------|
| **P0** | Core linter 9 NEW violations, D5 B2/B3 (39 ext violations) |
| **P1** | 4 missing protocol handlers (ws/webhook/express/sse), capability gate wire to facade helper (17 callsites) |
| **P2** | DSN driver check, `sub_workflow` DSL method, AI DSL exposure, `core/audit/facade.py` split |
| **P3** | Streamlit feature-grouping, slow ratchet, control_flow.py review, S3 ops completeness |
