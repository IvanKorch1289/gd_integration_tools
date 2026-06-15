# S126 Sprint Plan — 2-Sprint Roadmap (S127-S128)

> **Date:** 2026-06-14
> **Source:** `s126_verification_matrix.md` (22-domain verified state) + `tech_debt_register.md` (S111)
> **Constraint:** MAX 2 sprints per planning cycle (anti-bloat rule)
> **Score target:** 9.5 → 9.7 over 2 sprints

---

## Pre-Sprint State (S126)

| Metric | Value | Source |
|--------|-------|--------|
| Open P0/P1 tech debt | 9 items | tech_debt_register.md + 8 NEW (TD-020..TD-028) + TD-030 |
| Layer linter violations | 15 NEW core + 10 NEW ext (regression S117-S126) | check_layers.py output |
| Stale allowlist entries | 17 | check_layers.py output |
| Tests passing | ~10,800 (with 9-12 pre-existing failures) | pytest baseline |
| DSL processors | 229 | `find src/backend/dsl/engine/processors -name "*.py"` |
| Extensions | 4 active (core_entities, credit_pipeline, example_plugin, test_plug) | `ls extensions/` |
| Cookbooks | 6 (01-06) | `ls docs/cookbooks/` |
| ADRs | 165 | `ls docs/adr/ \| wc -l` |
| Docstring allowlist | 444 lines | `wc -l tools/check_docstrings_allowlist.txt` |

---

## Sprint S127 — "Quick wins + Variable Store + ExternalDB refactor" (5 waves)

**Goal:** Close TD-030 (P3 quick win) + TD-020 (P1 DSL gap) + TD-021 (P1 facade) + TD-022 partial
(P1 AI economy) + start TD-031 (layer linter regression).
**Score:** 9.5 → 9.6

### W1 — Quick wins: CB-1 cleanup + linter regression start (1 commit)

| Aspect | Detail |
|--------|--------|
| **Items** | TD-030 (P3 quick win) + TD-031 partial (5-10 of 25 linter violations) |
| **Files to change** | `core/utils/circuit_breaker.py` (delete), `core/utils/pybreaker_adapter.py` (delete), `core/resilience/breaker.py` (verify canonical, add re-export shim if needed), `tools/check_layers_allowlist.txt` (remove stale entries) |
| **Files to verify** | All callsites of deleted modules (search for `from core.utils.circuit_breaker` and `from core.utils.pybreaker_adapter`) |
| **New tests** | Regression test in `tests/unit/core/utils/test_circuit_breaker_removed.py` (imports should fail) |
| **Commit** | `chore(s127-w1-cb1): remove duplicate circuit_breaker.py + pybreaker_adapter.py, fix 5 layer violations` |
| **Risk** | LOW — these are duplicates; canonical `core/resilience/breaker.py` exists since S100 |
| **Time** | ~30 min (CB-1) + 1-2 hours (linter) = ~2 hours total |
| **W1 verification** | `rg "from src.backend.core.utils.circuit_breaker\|from src.backend.core.utils.pybreaker_adapter" src/ tests/ extensions/` = 0; `tools/check_layers.py` shows -5+ violations |

### W2 — TD-020: DSL Variable Store (VAR-1) (1 commit)

| Aspect | Detail |
|--------|--------|
| **Items** | TD-020 (P1 DSL gap — REAL at S126) |
| **Files to create** | `core/dsl/variables.py` (`DSLVariableStore` class), `core/dsl/variables_resolver.py` (`${var('key')}` parser), `dsl/engine/processors/variable_resolve.py` (processor) |
| **Files to modify** | `dsl/yaml_loader/loaders.py` (integrate `${var('key')}` resolution), `dsl/builders/base.pyi` (add `.variable()` method stub) |
| **Backends** | 1) ConsulConfigStore (S36 P4 already exists), 2) PostgreSQL `dsl_variables` table (new migration), 3) InMemoryDict (tests/dev) |
| **API** | `await DSLVariableStore.get(key, scope="global")`; `await DSLVariableStore.set(key, value, scope, ttl=None)`; hot-reload via Consul watch |
| **Builder method** | `RouteBuilder.variable(key, default=None, scope="global")` — resolves at route-execution time |
| **New tests** | `tests/unit/core/dsl/test_variable_store.py` (3 backends, hot-reload, TTL), `tests/unit/dsl/builders/test_variable_mixin.py` (builder method), `tests/unit/dsl/processors/test_variable_resolve.py` (processor) |
| **Commit** | `feat(s127-w2-vars): DSLVariableStore with ${var('key')} resolver + Consul/Postgres/Memory backends` |
| **Risk** | MEDIUM — adds new file + new expression syntax. Must NOT break existing `${body.field}` / `${env:VAR}` resolvers. |
| **Time** | ~3-4 hours (3 backends + tests) |
| **W2 verification** | All existing DSL routes still parse; new tests pass; no regression in `${body.field}` tests |

### W3 — TD-021: ExternalDBFacade + PoolingProfile migration (1 commit)

| Aspect | Detail |
|--------|--------|
| **Items** | TD-021 (P1 facade gap — REAL at S126) |
| **Files to create** | `core/db/external_facade.py` (`ExternalDBFacade` class with `query`/`execute`/`call_procedure`/`transaction`) |
| **Files to modify** | `core/config/external_databases/item.py` (migrate flat pool fields → `pooling: PoolingProfile`), `core/config/pooling.py` (verify completeness), `infrastructure/database/database/registry.py` (add `get_facade()` method) |
| **API** | `async def query(profile, sql, params={}) -> list[dict]`; `async def execute(profile, sql, params={}) -> int`; `async def call_procedure(profile, name, params={}) -> Any`; `@asynccontextmanager async def transaction(profile)` |
| **Connection pool** | Reuse `core/config/pooling.py:PoolingProfile` (S125+) — min_size, max_size, acquire_timeout, idle_timeout |
| **New tests** | `tests/unit/core/db/test_external_facade.py` (pooling, transactions, error paths), `tests/unit/core/config/test_item_pooling.py` (migration regression) |
| **Commit** | `refactor(s127-w3-extdb): migrate item.py to PoolingProfile + add ExternalDBFacade with query/execute/call_procedure/transaction` |
| **Risk** | MEDIUM — `item.py` is a Pydantic model; flat → nested requires migration + backward-compat shim |
| **Time** | ~3-4 hours (facade + migration + tests) |
| **W3 verification** | `ExternalDatabaseRegistry.get_initializer()` still works (backward-compat); new `get_facade()` works; `PoolingProfile` defaults match old flat fields |

### W4 — TD-022 partial: Prompt Caching for Anthropic (1 commit)

| Aspect | Detail |
|--------|--------|
| **Items** | TD-022 (P1 AI economy — REAL at S126) |
| **Files to create** | `infrastructure/ai/prompt_cache_middleware.py` (cache_control injection for anthropic/* models) |
| **Files to modify** | `core/ai/gateway.py` (`_build_messages` pipeline — add cache_control injection step), `infrastructure/ai/anthropic_provider.py` (verify integration) |
| **Mechanism** | For `model.startswith("anthropic/")`: inject `cache_control: {"type": "ephemeral"}` in system message + first tool_definitions block |
| **Economy** | 50-90% token savings on repeated system prompts (per Anthropic docs) |
| **New tests** | `tests/unit/infrastructure/ai/test_prompt_cache_middleware.py` (cache_control injection for anthropic, skip for openai), `tests/unit/core/ai/test_gateway_prompt_cache.py` (pipeline integration) |
| **Commit** | `feat(s127-w4-prompt-cache): AIGateway._build_messages inject cache_control: ephemeral for anthropic/* models` |
| **Risk** | LOW-MEDIUM — additive middleware, no behavior change for non-anthropic models |
| **Time** | ~2-3 hours |
| **W4 verification** | Token count for repeated system prompt < 50% of original; no behavior change for non-anthropic |

### W5 — ADR + CHANGELOG + remaining linter cleanup (1 commit)

| Aspect | Detail |
|--------|--------|
| **Items** | TD-031 partial (remaining 10-15 linter violations) + ADR-0214 + CHANGELOG |
| **Files to modify** | `tools/check_layers_allowlist.txt` (bulk update), `docs/adr/0214-sprint-127-closure.md` (NEW), `CHANGELOG.md` |
| **Commit** | `docs(s127-w5-closure): ADR-0214 sprint 127 closure + CHANGELOG + remaining linter cleanup` |
| **Time** | ~1-2 hours |

### S127 Total Time: ~12-15 hours (3 days)

**S127 deliverables:**
- TD-030 CLOSED (2 files deleted, 1 regression test)
- TD-020 CLOSED (3 backends + DSL integration + 3 test files)
- TD-021 CLOSED (ExternalDBFacade + PoolingProfile migration)
- TD-022 PARTIAL (cache_control for anthropic; OpenAI cache + provider-agnostic refactor in S128)
- TD-031 PARTIAL (-15 to -20 of 25 layer violations)
- Score: 9.5 → 9.6

---

## Sprint S128 — "Protocols expansion + Frontend refactor" (5 waves)

**Goal:** Close TD-024 (CERT-1) + TD-023 (CDC-2) + TD-025 (DIST-1) + TD-026 (FT-1) + TD-022 cont.
+ TD-013 (Frontend refactor) + finish TD-031.
**Score:** 9.6 → 9.7

### W1 — TD-024: Consul CertStore backend (1 commit)

| Aspect | Detail |
|--------|--------|
| **Items** | TD-024 (P1 cert gap — REAL at S126) |
| **Files to create** | `infrastructure/cert/consul_cert_backend.py` (ConsulCertStore class) |
| **Files to modify** | `core/config/cert_store.py` (add `"consul"` to `Literal`), `infrastructure/cert/factory.py` (add Consul branch) |
| **Fallback chain** | Vault → Consul → PostgreSQL → MongoDB → Memory (existing order; Consul inserted between Vault and PG) |
| **New tests** | `tests/unit/core/config/test_cert_store_consul.py` (Consul backend, fallback chain, error paths) |
| **Commit** | `feat(s128-w1-cert-consul): CertStore backend=consul + consul_cert_backend.py` |
| **Risk** | LOW — additive; existing backends unchanged |
| **Time** | ~2 hours |

### W2 — TD-023 + TD-025: CDC Transform + DaskMixin (1 commit, dual feature)

| Aspect | Detail |
|--------|--------|
| **Items** | TD-023 (P1 CDC gap) + TD-025 (P1 DSL gap) |
| **Files to create** | `dsl/engine/processors/cdc_transform.py` (transforms Debezium `{op/before/after}` + pgoutput `{operation/old/new}` to canonical CDCEvent); `dsl/builders/dask_mixin.py` (`.dask_compute()` method) |
| **Files to modify** | `dsl/builders/cdc_sources_mixin.py` (add `.transform_cdc_event()` method); `dsl/builders/base/__init__.py` (MRO — register DaskMixin) |
| **Existing assets** | `DaskComputeProcessor` in `dsl/engine/processors/dask_compute.py` (V7.1); `DaskBackend` in `infrastructure/execution/dask_backend.py` (lazy LocalCluster init) |
| **New tests** | `tests/unit/dsl/processors/test_cdc_transform.py` (both Debezium + pgoutput formats), `tests/unit/dsl/builders/test_dask_mixin.py` (builder method, scheduler_address) |
| **Commit** | `feat(s128-w2-cdc-dask): cdc_transform.py + cdc_sources_mixin.transform_cdc_event + dask_mixin.py` |
| **Risk** | MEDIUM — DaskMixin MRO registration; CDC format parsing must handle edge cases |
| **Time** | ~3-4 hours |

### W3 — TD-026 + TD-022 cont.: gRPC File Streaming + OpenAI cache (1 commit)

| Aspect | Detail |
|--------|--------|
| **Items** | TD-026 (P1 gRPC gap) + TD-022 continuation (OpenAI cache) |
| **Files to modify** | `entrypoints/grpc/protobuf/files.proto` (add `DownloadFile` server-streaming + `UploadFile` client-streaming + `FileChunk` message), `entrypoints/grpc_server/base.py` (implement streaming methods), `infrastructure/ai/openai_provider.py` (add cache_control for openai/gpt-4-turbo + gpt-4o) |
| **gRPC streaming** | `message FileChunk { bytes data = 1; string filename = 2; int32 index = 3; bool is_last = 4; }`; `rpc DownloadFile(GetFileRequest) returns (stream FileChunk); rpc UploadFile(stream FileChunk) returns (UploadFileResponse)` |
| **OpenAI cache** | Add `prompt_cache_key` parameter for OpenAI models that support it (gpt-4o, gpt-4-turbo with caching) |
| **New tests** | `tests/unit/entrypoints/grpc/test_file_streaming.py` (download + upload), `tests/unit/infrastructure/ai/test_openai_cache.py` |
| **Commit** | `feat(s128-w3-grpc-files): files.proto DownloadFile/UploadFile + base.py impl + OpenAI prompt cache` |
| **Risk** | MEDIUM — proto changes require regen of `_pb2*.py` files; OpenAI cache may not be GA yet |
| **Time** | ~3-4 hours |

### W4 — TD-013 + TD-031 final: Frontend refactor + linter closure (1 commit)

| Aspect | Detail |
|--------|--------|
| **Items** | TD-013 (P2 Frontend — per-page feature split) + TD-031 final (5-10 remaining linter violations) |
| **Files to modify** | `src/frontend/streamlit_app/` (group 117 .py files into per-feature subdirs: `pages/{ai,cdc,workflow,admin,monitoring}/` etc.), `tools/check_layers_allowlist.txt` (final cleanup) |
| **Strategy** | Per-feature grouping: identify top 10 most-used pages; create `pages/<feature>/__init__.py` + move page files; keep shared `components/` and `services/` |
| **New tests** | `tests/unit/frontend/test_streamlit_pages.py` (verify all pages importable after refactor) |
| **Commit** | `refactor(s128-w4-frontend): streamlit per-page feature grouping + final linter cleanup` |
| **Risk** | MEDIUM — refactor of 117 files; risk of breaking import paths |
| **Time** | ~4-5 hours (careful refactor) |

### W5 — ADR + CHANGELOG (1 commit)

| Aspect | Detail |
|--------|--------|
| **Items** | ADR-0215 + CHANGELOG + final score 9.7 |
| **Files to modify** | `docs/adr/0215-sprint-128-closure.md` (NEW), `CHANGELOG.md` |
| **Commit** | `docs(s128-w5-closure): ADR-0215 sprint 128 closure + CHANGELOG` |
| **Time** | ~1-2 hours |

### S128 Total Time: ~13-17 hours (3-4 days)

**S128 deliverables:**
- TD-024 CLOSED (Consul CertStore backend)
- TD-023 CLOSED (TransformCdcEventProcessor)
- TD-025 CLOSED (DaskMixin in RouteBuilder)
- TD-026 CLOSED (gRPC DownloadFile/UploadFile streaming)
- TD-022 CLOSED (Prompt cache for anthropic + openai)
- TD-013 PARTIAL (per-page feature split; 10 most-used pages grouped)
- TD-031 CLOSED (linter regression fully fixed; -25 violations)
- Score: 9.6 → 9.7

---

## Sprint S129+ (deferred to next planning cycle)

| ID | Item | Priority | Estimated time |
|----|------|----------|----------------|
| TD-027 | S3 Runtime Fallback (purgatory CB + `infrastructure/storage/fallback_storage.py`) | P1 | ~3 hours |
| TD-028 | CodecFacade (`core/codec/facade.py` with json/msgpack/avro/cbor/base64/protobuf) | P2 | ~3 hours |
| TD-029 | DB Streaming cursor + db_transaction DSL block | P2 | ~4 hours |
| TD-005 | DSN driver availability check (runtime risk with optional deps) | P1 | ~1 hour |
| TD-007 | Capability gate wiring (17 callsites still use legacy `self._audit: Callable`) | P1 | ~30 min |
| TD-015 | DSL processor collection errors (3 files) | P3 | ~1 hour |
| TD-016 | smart_session_manager_wire TypeError fix | P3 | ~1 hour |
| TD-009 | sub_workflow DSL method (S93 W5 partial) | P2 | ~1 hour |
| TD-010 | DSL AI exposure (ai_invoke, ai_tool_dispatch) | P2 | ~3 hours |
| TD-011 | DSL source methods (NATS, Mongo, gRPC stream) | P2 | ~3 hours |
| TD-014 | control_flow.py (416 LOC) review for split | P3 | ~1 hour |

---

## Sprint capacity check (anti-bloat rule)

| Sprint | W1 | W2 | W3 | W4 | W5 | Total | Capacity |
|--------|----|----|----|----|----|-------|----------|
| S127 | CB-1 + linter | VAR-1 | FACADE-2 | Prompt cache | ADR | ~12-15h | OK (1 day/feature) |
| S128 | CERT-1 | CDC + Dask | gRPC + OpenAI | Frontend + linter | ADR | ~13-17h | OK (1 day/feature) |

**Both sprints respect the anti-bloat rule:** ≤ 5 waves, ≤ 1 day per feature, ≤ 3 sprints per planning cycle.

---

## Risk register

| Risk | Sprint | Mitigation |
|------|--------|-----------|
| v4 prompt paths may have further drift (S127-S128 changes) | Both | Run 5-sec factcheck on EVERY claim before commit |
| Layer linter regression may grow | Both | Run `tools/check_layers.py` BEFORE commit; add to pre-commit hook |
| mem0ai / guardrails-ai add attempts | Both | Reference R11 in master prompt; cross-check pyproject.toml before any dep add |
| AI-6 prompt cache may not be GA for OpenAI | S128 W3 | Conditional: `if model in {anthropic/*, openai/gpt-4-turbo, openai/gpt-4o}` |
| gRPC proto regen breaks client code | S128 W3 | Add backward-compat shim for old RPCs (both GetFile + DownloadFile) |
| Frontend refactor breaks import paths | S128 W4 | Add `tests/unit/frontend/test_streamlit_pages.py` to verify all pages importable |
| Frontend per-page split is cosmetic — low value | S128 W4 | If < 4 hours saved by refactor, defer to S129+ |

---

## Definition of "Sprint success"

- ✅ 5 atomic commits per sprint (one per wave)
- ✅ All targeted TD items closed (or explicitly marked PARTIAL with reason)
- ✅ 0 NEW regressions in test suite (compared to S126 baseline)
- ✅ Layer linter violations DECREASED (target: -10 per sprint)
- ✅ Docstring ratchet maintained (target: -10 per sprint)
- ✅ ADR + CHANGELOG updated at W5
- ✅ Score increased (target: 9.5 → 9.6 → 9.7)

**Sprint FAIL condition:** net tech debt INCREASED (i.e., NEW violations > CLOSED violations).

---

## References

- `reports/reaudit/s126_verification_matrix.md` (this era's 22-domain state)
- `reports/reaudit/master_prompt_for_agent.md` (S126 master prompt — replaces S109)
- `reports/reaudit/tech_debt_register.md` (S111 state — needs S127 refresh)
- `reports/reaudit/findings.md` (S109 30-point matrix — partially stale)
- `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-06-12.md` (S92 era, partially stale)
- `gap-analysis/MASTER-PROMPT-factcheck-plan-execute.md` (S109 fact-check)
- S109 closure: `git log --oneline -1` (S109 W5)
- Latest ADR: `docs/adr/0213-sprint-125-closure.md`
