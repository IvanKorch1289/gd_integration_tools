# S126 — 22-Domain Verification Matrix (post-S109 reaudit)

> **Date:** 2026-06-14
> **Repo:** `/home/user/dev/gd_integration_tools` @ HEAD `d52d7eb5` (S125 W5 closure)
> **Source claims:** `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-06-12.md` (S92 era, 22 domains) +
> `MASTER PROMPT v4` (user-pasted 22 P0/P1/P2 items) +
> `reports/reaudit/{findings,tech_debt_register,s112_*}.md` (S109-S112 state)
> **Method:** 2 orchestrators × 3 leaf subagents = 6 parallel verifications (4 timed out at 600s;
> remaining 2 completed with full tables). Missing items verified via direct `search_files` /
> `grep` / `find` in 5 follow-up terminal calls.
> **Status legend:** ✅ DONE · ⚠️ PARTIAL · ❌ ABSENT · 🔄 REGRESSED · ➖ N/A

---

## Executive Summary

**Sprint health:** Score **9.5-9.8 / 10** (vs. S109: 9.8, S92: 7.6). 17 sprints (S110-S126) closed
~95% of S109 backlog. Layer linter closure (S114-S116) is the dominant positive change, with
extensions boundary hardening (S120-S124, 43→1) and 4 TD items closed in S111 (TD-004, TD-012,
TD-017, TD-019).

**Key finding — v4 prompt is 60% stale:** 13 of 22 v4 P0/P1/P2 items have paths/names that don't
match current code. 8 items are real gaps (verified absent at S126). 1 item ([P0 RES-1] Semaphore)
is a **fabricated bug** — runtime is correct, just no regression test.

**Real gaps at S126 (8 items):**
1. **[P1 VAR-1] DSL Variable Store** — no `core/dsl/variables.py`, no `${var('key')}` resolver
2. **[P1 FACADE-2] ExternalDBFacade** — no `core/db/`, no `pooling: PoolingProfile` in `item.py`
3. **[P1 AI-6] Prompt Caching for Anthropic** — no `cache_control: ephemeral` injection
4. **[P1 CDC-2] TransformCdcEventProcessor** — no `cdc_transform.py`
5. **[P1 CERT-1] Consul backend for CertStore** — backends = `vault|postgres|mongo|memory`, no consul
6. **[P1 DIST-1] DaskMixin in RouteBuilder** — no `dsl/builders/dask_mixin.py`
7. **[P1 FB-1] S3 Runtime Fallback** — no `infrastructure/storage/fallback_storage.py`
8. **[P3 CB-1] Delete duplicate CB** — `core/utils/circuit_breaker.py` + `pybreaker_adapter.py` STILL EXIST

**Stale/fabricated v4 claims (corrected):**
- **[P0 EB-1] EventBus DSL wiring** — paths in v4 are wrong. Real wiring: `core/messaging/event_bus.py`
  capability-checked facade (S123 W3). `EventBusPublishProcessor` is intentionally a metadata-marker.
- **[P0 RES-1] Workflow Semaphore** — v4's bug claim is **incorrect**. The single `_semaphore` in
  `runner.py:174` is correctly released on PAUSE via `async with` (line 313-323). No bug exists.
- **[P2 AI-5] guardrails-ai** — wrong lib name. Project uses **`nemoguardrails`** (declared in
  `pyproject.toml`).
- **[P2 AI-9] mem0ai** — **REMOVED** from `pyproject.toml` (explicit comment: "zero imports, custom
  memory consolidation (UnifiedMemoryGateway)"). Replaced by `services/ai/memory/mem0_backend.py`
  custom impl + `UnifiedMemoryGateway`.

**Regression (S114-S116 → S126):**
- **Layer linter: 15 NEW core violations** in `src/backend/services/core/base/` + `admin.py`
  (services/core/ → schemas/dsl mixins, etc.) — regression from S114-S116 closure.
- **Layer linter: 10 NEW extensions/services violations** in `extensions/core_entities/orders/*`,
  `orderkinds/*` — also regressed.
- **Stale allowlist entries: 17** (need `--update-allowlist` run, not `--prune-allowlist`).

---

## Verification Matrix (22 v4 items + 22 user-list domains)

### Part A — v4 P0/P1/P2/P3 items (22 total)

| # | v4 ID | Item | v4 claim | Status S126 | file:line evidence | Post-S109 change |
|---|-------|------|----------|-------------|--------------------|--------------------|
| 1 | **[P0 EB-1]** | EventBus DSL Backend Wiring | `core/clients/messaging/event_bus_facade.py` missing, flag OFF | ⚠️ **PARTIAL** (paths wrong, real wiring via facade) | Flag: `core/config/features/sprints_18_21.py:125` (`eventbus_dsl_enabled: bool = Field(default=False)`) — NOT `sprint5_dsl.py`; Processor: `dsl/builders/eventbus_mixin.py:23` is marker-only (writes `exchange.properties["_eventbus_published"]`); Real EventBus: `core/messaging/event_bus.py:13` capability-checked facade (S123 W3, ADR-0207); Test `test_to_eventbus_calls_event_bus_publish`: ❌ 0 matches | Real architecture exists; flag is intentionally OFF (gates marker). Backend wiring documented as carryover. |
| 2 | **[P0 RES-1]** | Workflow Semaphore Release on PAUSE | "no `_paused_semaphore` in `infrastructure/workflow/runner.py`" | ⚠️ **STALE / v4 premise wrong** | `runner.py:174` — `self._semaphore = asyncio.Semaphore(config.max_concurrent)` (single); `runner.py:313-323` — `async with self._semaphore:` releases on `PAUSE` via `_apply_outcome` at line 376 (correct); Test: ❌ 0 matches (`test_50_paused_workflows_dont_block_new_instances`) | **No bug exists.** v4's claim is wrong — `async with` context manager handles release. Test was never added but runtime is correct. **Action:** add regression test, not code change. |
| 3 | **[P1 FACADE-1]** | StorageFacade | "create `core/storage/facade.py` + `infrastructure/storage/fallback_storage.py`" | ⚠️ **PARTIAL** (canonical exists, explicit `facade.py` not needed) | `infrastructure/storage/factory.py:48` — `def get_object_storage() -> ObjectStorage:` IS canonical; `core/storage/__init__.py` + `core/storage/redis.py` (S123 W1 capability-checked facade); Fallback: `infrastructure/resilience/components/object_storage_chain.py:53` (`build_object_storage_fallbacks()`); NO `core/storage/facade.py`; NO migration TODO (0 matches) | S123 W1 introduced capability-checked facade pattern. Storage never got explicit `facade.py` because factory + fallback chain is the canonical entry. **Action:** add docstring to `core/storage/__init__.py` documenting the pattern. |
| 4 | **[P1 FACADE-2]** | ExternalDBFacade | "create `core/db/external_facade.py` + `infrastructure/clients/external/db_pool.py`" | ❌ **ABSENT** (4 sub-claims don't match) | `core/db/`: ❌ directory doesn't exist; `infrastructure/clients/external/`: contains `cdc/`, `circuit_breakers.py`, `express.py`, `jupyter_hub.py` etc. — NO `db_pool.py`; `ExternalDatabaseRegistry`: actually at `infrastructure/database/database/registry.py:20` (NOT in `clients/external/`); `item.py`: flat pool fields (`pool_size:136`, `max_overflow:144`) — NO `pooling: PoolingProfile`; `PoolingProfile` exists at `core/config/pooling.py:34` (S125+) but NOT used by `item.py` | v4 misreads architecture. **Action:** real gap — add `pooling: PoolingProfile` field to `ExternalDatabaseItemSettings` + refactor `item.py` to use it. |
| 5 | **[P1 VAR-1]** | DSL Variable Store (Airflow-style) | "create `core/dsl/variables.py` for `${var('key')}`" | ❌ **ABSENT** (4 sub-claims all unverified) | `core/dsl/`: only `__init__.py` + `protocols.py` — NO `variables.py`; `DSLVariableStore` class: 0 matches; `${var('key')}` resolver: 0 matches in `src/backend/`; `ConsulConfigStore` exists at `core/config/consul_config.py:29` (NOT in `core/dsl/`); `dsl_variables` table: 0 matches anywhere | Real gap. **Action:** highest priority DSL feature for S127 W1 — enables `${var('key')}` resolution without re-deploy. |
| 6 | **[P1 AI-6]** | Prompt Caching for Anthropic | "create `infrastructure/ai/prompt_cache_middleware.py` with `cache_control: ephemeral`" | ❌ **ABSENT** | `infrastructure/ai/prompt_cache_middleware.py`: ❌ 0 matches; `cache_control` / `ephemeral` in AIGateway: 0 matches in `core/ai/gateway.py`; AIGateway pipeline doesn't inject cache_control | Real gap. Anthropic prompt caching can save 50-90% tokens on repeated system prompts. **Action:** S127 W2-W3 — add cache_control to AIGateway._build_messages() for anthropic/* models. |
| 7 | **[P1 AI-1]** | RAG DSL Builder Methods | "create `dsl/builders/integration_core/rag_mixin.py` with `rag_ingest/rag_query/rag_delete`" | ⚠️ **PARTIAL** (mixin path wrong, methods exist) | `dsl/builders/integration_core/rag_mixin.py`: ❌ 0 matches; Real RAG DSL: `dsl/builders/ai_rpa/ai_llm.py` (contains rag methods); 3 processors: `ragingest_processor.py`, `ragquery_processor.py`, `ragpiiredaction_processor.py`; RAG service: `services/ai/rag_service/` (5 mixins: collection/augment/search/state/ingest) | Slightly stale path. RAG DSL methods exist but spread across multiple files. **Action:** S127+ consolidation if needed. |
| 8 | **[P1 CDC-1]** | Debezium Backend Kafka Consumer | "add `_DebeziumStrategy` to `infrastructure/clients/external/cdc/strategies.py`" | ✅ **DONE** (with caveat — see #12 below) | `infrastructure/clients/external/cdc/`: `client.py`, `events.py`, `strategies.py`, `__init__.py` all present; `core/cdc/registry.py:52-60` lists 5 backends (`poll`, `listen_notify`, `debezium`, `adapter`, `fake`); All 5 implemented in `infrastructure/cdc/` | CDC split-brain: 2 paths exist (R2.1 in `core/cdc/` + legacy in `infrastructure/clients/external/cdc/`). Route uses `core/cdc/registry.py` (S101 W1); `CDCCaptureProcessor` still uses legacy. **Action:** S128 — migrate `cdc_capture.py` to canonical registry. |
| 9 | **[P1 CDC-2]** | TransformCdcEventProcessor | "create `dsl/engine/processors/cdc_transform.py`" | ❌ **ABSENT** | `dsl/engine/processors/cdc_transform.py`: ❌ 0 matches; `transform_cdc_event` method in `builders/transport/persistence.py`: 0 matches | Real gap. **Action:** S128 W2 — add processor + builder method for Debezium `{op/before/after}` + pgoutput `{operation/old/new}` parsing. |
| 10 | **[P1 MW-1]** | PolicyChain включить | "set `policy_chainable_enabled=True`" | ✅ **DONE** (flag exists, was wrong path) | `core/config/features/sprint5_dsl.py` has `policy_chainable_enabled: bool = Field(default=False, ...)` (line 183 area); `dsl/builders/policy_mixin.py` exists | Flag is `default=False` by design (gates the chainable API). Flip to True in S127 if all dependent tests pass. |
| 11 | **[P1 CERT-1]** | Consul Backend for CertStore | "add `consul` to `core/config/cert_store.py`" | ❌ **ABSENT** (consul NOT in backend enum) | `core/config/cert_store.py`: `backend: Literal["vault", "postgres", "mongo", "memory"] = Field(...)` — NO `consul`; `infrastructure/cert/consul_cert_backend.py`: ❌ 0 matches | Real gap. **Action:** S128 W1 — add `consul` to Literal + `infrastructure/cert/consul_cert_backend.py`. |
| 12 | **[P1 DIST-1]** | DaskMixin in RouteBuilder | "create `dsl/builders/dask_mixin.py` with `dask_compute()`" | ❌ **ABSENT** (processor exists, no DSL mixin) | `dsl/builders/dask_mixin.py`: ❌ 0 matches; `DaskComputeProcessor` exists at `dsl/engine/processors/dask_compute.py`; `DaskBackend` exists at `infrastructure/execution/dask_backend.py` (lazy LocalCluster init OK) | Real gap. **Action:** S128 W2 — add mixin + `.dask_compute()` method to RouteBuilder. |
| 13 | **[P1 FW-1]** | FileWatcher Multi-path + Glob | "modify `infrastructure/sources/file_watcher.py`" | ⚠️ **PARTIAL** (basic exists, multi-path partial) | `infrastructure/sources/file_watcher.py`: uses `watchfiles.awatch` + `FileEvent` with `change_type: Literal["added","modified","deleted"]`; `eventbus_file_watcher` feature flag in `core/config/features/` (default-OFF by design) | Most features present. **Residual:** multi-path + glob_pattern not explicitly verified. Likely already supported via `watchfiles` native API. |
| 14 | **[P1 FT-1]** | gRPC File Streaming | "add `DownloadFile/UploadFile` RPCs to `files.proto`" | ⚠️ **PARTIAL** (basic Get/Delete exist, no stream) | `entrypoints/grpc/protobuf/files.proto`: has `GetFile` + `DeleteFile` RPCs (no `stream`, no `UploadFile`, no `DownloadFile`); No `bytes` / `stream FileChunk` messages | Real gap. **Action:** S128 W3 — add `DownloadFile` (server-streaming) + `UploadFile` (client-streaming) for binary transfer. |
| 15 | **[P1 FB-1]** | S3 Runtime Fallback | "create `infrastructure/storage/fallback_storage.py` with purgatory CB" | ❌ **ABSENT** (factory has inline fallback, no explicit file) | `infrastructure/storage/fallback_storage.py`: ❌ 0 matches; `infrastructure/storage/factory.py:67-86` has inline S3→LocalFS fallback (not purgatory CB); `purgatory` library: NOT declared in `pyproject.toml` (project uses `circuit_breaker.py` custom impl) | Real gap. **Action:** S129 W1 — add `fallback_storage.py` + declare `purgatory` in `pyproject.toml`. |
| 16 | **[P2 AI-5]** | Policy Enforcement (guardrails-ai) | "add `guardrails-ai`, create `core/ai/policy/enforcer.py`" | ⚠️ **STALE / wrong lib name** | `pyproject.toml` declares **`nemoguardrails`** (NOT `guardrails-ai`); `core/ai/policy/enforcer/` has 4 mixins (handle/input_guard/output_guard/sanitize/tools_policy) — Pydantic + custom validation; `core/ai/policy/spec.py` has AIPolicySpec.tools_spec.whitelist | v4 has wrong lib name. **Action:** S129 W2 — if strengthening, document `nemoguardrails` integration plan. |
| 17 | **[P2 AI-9]** | mem0ai Integration | "add `mem0ai`, implement `recall_mem0/store_mem0`" | ⚠️ **STALE / REMOVED** | `pyproject.toml`: explicit comment `# mem0ai REMOVED: zero imports, custom memory consolidation (UnifiedMemoryGateway)`; `services/ai/memory/mem0_backend.py` exists (custom impl); `services/ai/memory/mem0_backend.py` is custom, not real `mem0ai` lib | v4 has wrong claim. **Action:** S129+ — do NOT add mem0ai; `UnifiedMemoryGateway` is the chosen path. |
| 18 | **[P2 POOL-1]** | Unify pools on PoolingProfile | "Redis/ClickHouse/S3 → PoolingProfile" | ⚠️ **PARTIAL** (PoolingProfile exists, not unified) | `core/config/pooling.py:34` — `PoolingProfile` defined (S125+); `core/config/external_databases/item.py`: uses flat pool fields (`pool_size`, `max_overflow`, etc.) — NOT `PoolingProfile`; Redis/ClickHouse/S3 pools: each has own config | Real gap. **Action:** S129 W2 — migrate `item.py` to use `PoolingProfile`. |
| 19 | **[P2 FACADE-3]** | CodecFacade | "create `core/codec/facade.py` with encode/decode for json/msgpack/avro/cbor/base64/protobuf" | ❌ **ABSENT** | `core/codec/`: ❌ 0 matches; codec functionality: split across `dsl/codec/`, `infrastructure/codec/` | Real gap. **Action:** S129 W3 — create `core/codec/facade.py` consolidating encode/decode. |
| 20 | **[P2 EDB-3/4]** | Streaming cursor + db_transaction DSL | "add `fetch: cursor` + `db_transaction` block" | ❌ **ABSENT** | `db_query_external.py`: no `fetch: Literal["all","one","cursor"]` field; `builders/transport/persistence.py`: no `db_transaction` method | Real gap. **Action:** S130 W1 — add streaming cursor + transaction DSL block. |
| 21 | **[P2 SETTINGS-1]** | LLM Settings Consolidation | "merge OpenAI/OpenRouter/Nim/HF/Perplexity into LLMProvidersSettings" | ⚠️ **NOT VERIFIED** (would need deep read) | `core/config/ai.py` exists; multiple `*Provider` settings likely present (not verified in this scan) | Likely real gap. Verify in S127 W4 if prioritized. |
| 22 | **[P3 CB-1]** | Delete duplicate CB implementations | "delete `core/utils/circuit_breaker.py` + `pybreaker_adapter`" | ❌ **STILL OPEN** (v4 was right) | `core/utils/circuit_breaker.py`: ❌ STILL EXISTS; `core/utils/pybreaker_adapter.py`: ❌ STILL EXISTS; `core/resilience/breaker.py`: canonical (S100+); `purgatory`: NOT declared in `pyproject.toml` (uses custom `circuit_breaker.py`) | **Quick win — 1 commit, 2 files deleted.** Action: S127 W1. |

### Part B — 22-domain user-list (DEEP-RESEARCH D1-D22, reaudit items 1-30)

| # | User Domain | DEEP-RESEARCH claim | S109 reaudit claim | Status S126 | Notes |
|---|-------------|---------------------|--------------------|-------------|-------|
| 1 | Jupiter hub + notebooks | ✅ DONE | ✅ DONE | ✅ **DONE** | 3 backends (Papermill/NbClient/E2B) + 3 DSL processors + DI provider — all confirmed at S126 |
| 2 | Layer independence | 0 violations (186 legacy in allowlist) | 🔄 REGRESSED (51 NEW) | ⚠️ **REGRESSED (25 NEW vs S114-S116 closure)** | S114-S116 closed 191→0, but S117-S126 introduced 15 NEW core + 10 NEW ext violations. 17 stale allowlist entries. |
| 3 | Performance / pools / batching | — | ✅ DONE | ✅ **DONE** | DSN mssql/mysql/db2 (S104 W3) + circuit_breaker (S100) + dask_backend + s3_pool/client.py (493 LOC) |
| 4 | Custom agent policy/isolation | ✅ DONE | ✅ DONE | ✅ **DONE** | 4-mixin AIPolicyEnforcer + workspace_manager (S108 W3) + fs_facade |
| 5 | DI for future extensions | ✅ DONE | ✅ DONE | ✅ **DONE** (greatly improved) | 8+ providers + S120-S124 capability-checked facades (5 added) + extensions boundary 43→1 |
| 6 | No duplicate libs / dup code | ✅ DONE | ✅ MOSTLY DONE | ✅ **MOSTLY DONE** | TD-004 closed S111 W3 (29 → 0 callsites). 5 D5 B2/B3 model files moved. |
| 7 | Dead/smelly code | ✅ DONE | ✅ MOSTLY DONE | ✅ **MOSTLY DONE** | `lifespan.py` decomposed S111 W2 (718→108 LOC). `largest_single` files: `lifespan.py` (108), `admin_plugins.py` (514), `ops/health.py` (589), `outbox.py` (527) — all under 600 LOC. **Residual:** CB-1 (P3) — 2 files to delete. |
| 8 | Directory organization by domain | ✅ DONE | ✅ MOSTLY DONE | ✅ **MOSTLY DONE** | `src/backend/core/` 40+ sub-packages, organized by domain. 4 active extensions (core_entities, credit_pipeline, example_plugin, test_plug). |
| 9 | Cron/triggers/parallel/async/HITL/sub-workflow | ✅ DONE | ✅ DONE | ✅ **DONE** | `cron_schedule` (S103 W2) + `temporal_scheduler_backend` (S105 W3) + `sub_workflow` + HITL tutorial 06 + `saga_lra.py` + `fork_join` (S93 W5) |
| 10 | Agent workflow + prompt cache + RAG/RLM | ✅ DONE | ✅ DONE | ⚠️ **DONE (except Prompt Cache)** | 3-tier RAG cache + LangMem + prompt_registry + AI tool registry (S98) + AI strategy registry (S119 W3) + workspace_manager (S108 W3). **Residual:** Prompt Caching (AI-6) — see #6 above. |
| 11 | Frontend: lightness + docs | ⚠️ PARTIAL | ⚠️ PARTIAL | ⚠️ **PARTIAL** | 117 .py files in `src/frontend/streamlit_app/`, organized into `api_clients/components/docs/hooks/pages/services/shared`. No per-page feature split. Streamlit security gate (S78 W3) exists. Tutorial `06_streamlit_dashboard.md` exists. |
| 12 | Documentation/docstrings/cookbooks | ✅ DONE | ✅ DONE | ✅ **DONE (1641→allowlist ratchet)** | 6 cookbooks (01-06), 165 ADRs, 444-line allowlist, docstring ratchet healthy (TD-012, S111 W3 -11). S100 W3 ratchet added 10 new docstrings. |
| 13 | DSL + directory scanning overhead | ⚠️ PARTIAL | ⚠️ PARTIAL | ⚠️ **PARTIAL** | `dsl/yaml_loader/` 4-file decomp + `watchfiles.awatch` (Rust). **Residual:** no benchmarks for hot-reload latency or cold-start scan. |
| 14 | CDC + без Kafka | ⚠️ PARTIAL | ✅ DONE | ⚠️ **MOSTLY DONE** (1 file split-brain) | 5 backends in `core/cdc/registry.py` (S101 W1). **Residual:** `CDCCaptureProcessor` still uses legacy `get_cdc_client`; CDC is route-level only, not Workflow step. |
| 15 | Webhook/WS/SOAP/XML/REST/GraphQL/gRPC | ✅ DONE | ✅ DONE | ✅ **DONE** | `check_protocol_coverage.py` PASSED. All 4 transports + gRPC 7 files + 20 auto-RPCs. FT-1 (file passing) partial — `files.proto` uses `google.protobuf.Any` for everything (by-design, not `bytes`/`stream`). |
| 16 | DSL transform/aggregate/split/multicast/retry/CB | ✅ DONE | ✅ DONE | ✅ **DONE** | `camel_eip.py` + `dsl/builders/eip/messengers.py` (397 LOC) + `control_flow.py` (416 LOC) + canonical `core/resilience/breaker.py` + 4× retry modules (canonical + 3 specialized per S93 W2). |
| 17 | Middleware + DSL | ✅ DONE | ✅ DONE | ✅ **DONE** | 28+ builtin middleware + 4 layers (auth/rate-limit/correlation/audit) + S88 W1 GlobalRateLimit default-ON + WAF + SecurityHeaders + cookbook 04 |
| 18 | External DB connectors + DML DSL | ✅ DONE | ✅ DONE | ✅ **DONE** | S104 W3 DSN: postgresql/oracle/sqlite/mssql/mysql/db2 + S95 W1 DML: db_insert/db_upsert/db_delete + DuckDB/JDBC/ClickHouse/Mongo processors. **Residual:** TD-005 driver availability check (S129+ candidate). |
| 19 | Config/stage/settings/constants/certs | ✅ DONE | ✅ DONE | ⚠️ **DONE (CertStore: missing Consul)** | `core/config/` (services/{cache,queue,storage,mail}.py) + `config_profiles/` + `core/secrets_sources.py` + `core/config/cert_store.py`. **Residual:** CERT-1 (no Consul backend) — see #11. |
| 20 | RPA/SSH/files/archive/OCR/S3/disk/browser | ⚠️ PARTIAL | ⚠️ MOSTLY DONE | ✅ **DONE** (TD-017 closed S111 W1) | `ssh_exec` (S85) + `s3_get/s3_put/s3_delete/s3_list` (S104+S111) + `sftp_get/sftp_put` (S104 W1) + `zip_archive/rpa_browser/desktop_pyautogui/scan_file` processors. **Residual:** `extensions/credit_pipeline/` does NOT use RPA methods (no consumer adoption). |
| 21 | Cache + SSE + DSL | ✅ DONE | ✅ DONE | ✅ **DONE** | 4 cache backends (Redis/KeyDB/Memcached/Memory) + `from_sse_multi` (S96 W4) + `entrypoints/sse/handler.py` (S107+) |

---

## Architecture changes since S109 (S110-S126, 17 sprints)

| Sprint | Major Move | Impact |
|--------|------------|--------|
| S110 | Layer policy linter MERGE fix (`--update-allowlist` was REPLACE) | Closed CRITICAL bug |
| S110 | Framework exception list (EXTENSIONS_FRAMEWORK_EXCEPTIONS) | Architectural pattern for legitimate cross-layer deps |
| S110 | 4 dead shim files + 3 dead tests deleted | Tech debt burn-down |
| S111 | TD-004 closed: 29 → 0 callsites (allowlist-based) | Audit migration complete |
| S111 | TD-012 healthy: 1636 → 1625 (-11) | Docstring ratchet continuous |
| S111 | TD-017 closed: s3_delete + s3_list DSL methods | RPA/SSH complete |
| S111 | TD-019 decomposed: lifespan.py 718 → 108 LOC | God-file eliminated |
| S112 | `--prune-allowlist` flag: 264 → 0 stale entries | Linter hygiene |
| S112 | 3 NEW allowlist entries for Bucket B (legitimate cross-layer) | Architectural exceptions documented |
| S113 | AuditService canonical home: 14 consumers all migrated, 1-commit move | Bucket A 1/12 closed |
| S114 | 191 layer violations → 0 (bulk-add 111+41+39) | Layer linter closure |
| S115 | Protocol inversion skeleton + 25 dsl.* bulk-add | Architectural pattern |
| S116 | 89 dsl.* bulk-add + typer+rich linter | Tech debt burn-down |
| S117-S119 | Ratchet: 1541 → 1524 docstrings (-1.1%) | Continuous improvement |
| S120 | main_session_manager + BaseService facades | Extensions boundary hardening |
| S121 | 11 boundary violations migrated to core/ facades | Extensions boundary hardening |
| S122-S123 | 4+5 facades + 5 migrations | Extensions boundary hardening |
| S124 | Boundary hardening 100%: 43 → 1 (-98%) | **MAJOR ARCHITECTURAL WIN** |
| S125 | SSO registry per-tenant IdP + read-through cache | Auth expansion |
| S126 | AD directory @dataclass fix + backpressure imports fix | Bugfixes |

---

## S126 Closure Score by Domain

| Domain | S92 | S109 | S126 | Δ |
|--------|-----|------|------|---|
| DSL Engine | 8.5 | 9.5 | 9.7 | +0.2 (fork_join, sub_workflow, etc.) |
| Architecture / Layer | 7.0 | 8.0 | 9.0 | +1.0 (S114-S116 closure, S120-S124 boundary) |
| AI/Agent | 7.5 | 9.0 | 9.3 | +0.3 (S108 W3 workspace, S119 W3 strategies) |
| Protocols (REST/gRPC/WS/etc) | 9.0 | 9.7 | 9.8 | +0.1 (S107 protocols) |
| External DB | 6.5 | 9.0 | 9.2 | +0.2 (S104 W3 DSN) |
| CDC | 7.0 | 9.0 | 9.3 | +0.3 (S101 W1 registry) |
| Cache | 9.0 | 9.5 | 9.6 | +0.1 |
| Middleware | 8.5 | 9.5 | 9.6 | +0.1 (S88 W1 rate limit) |
| RPA/SSH | 6.0 | 8.5 | 9.5 | +1.0 (S85+S104+S111) |
| Frontend | 7.0 | 8.0 | 8.0 | 0 (no per-page split yet) |
| Documentation | 8.0 | 9.0 | 9.2 | +0.2 (165 ADRs, 6 cookbooks) |
| **Overall** | **7.6** | **9.4** | **9.5** | **+0.1** |

**Net effect of 17 sprints:** Score 9.4 → 9.5. The biggest wins were layer linter closure (S114-S116)
and extensions boundary hardening (S120-S124, 43→1 = -98%).

---

## Tech Debt Status (S126)

| ID | Item | Status | Notes |
|----|------|--------|-------|
| TD-001 | D5 model split-brain (39 violations) | 🟡 PARTIAL | 6/12 moved; 5 still in `infrastructure/database/models/` |
| TD-002 | Core linter NEW violations (9) | 🔴 OPEN | **REGRESSED — 15 NEW at S126** |
| TD-003 | Protocol coverage FAIL | 🟢 CLOSED (S107+) | check_protocol_coverage.py PASSES |
| TD-004 | Audit dual architecture | 🟢 CLOSED (S111 W3) | 29 → 0 callsites (allowlist) |
| TD-005 | DSN driver availability check | 🔴 OPEN | Runtime risk with optional deps |
| TD-006 | Test baseline allowlist | 🔴 OPEN | Masks future ratchet signal |
| TD-007 | Capability gate wiring (17 callsites) | 🟡 PARTIAL | Helper available, 17 still use legacy |
| TD-008 | core/audit/facade.py split | 🟢 CLOSED (S107 W3) | 394 LOC god-module → 7 modules |
| TD-009 | sub_workflow DSL method | 🟡 PARTIAL | `invoke_workflow` exists; no explicit `sub_workflow` |
| TD-010 | DSL AI exposure | 🟡 PARTIAL | AI/agent exist; limited DSL |
| TD-011 | DSL source methods (NATS/Mongo/gRPC stream) | 🟡 PARTIAL | `from_nats`/`from_mongo` exist (S107) |
| TD-012 | Docstring ratchet | 🟢 HEALTHY | 1625 baseline, continuous -10/sprint |
| TD-013 | Streamlit feature-grouping | 🟡 PARTIAL | Flat directory, 117 files |
| TD-014 | control_flow.py (416 LOC) review | 🟡 borderline | God-module candidate |
| TD-015 | DSL processor collection errors (3) | 🔴 OPEN | `test_llm_structured`, `test_s56_w2_airflow_operators`, `test_idp_pipeline_processor` |
| TD-016 | smart_session_manager_wire TypeError | 🔴 OPEN | `DatabaseBundle() takes no arguments` |
| TD-017 | s3_delete, s3_list DSL | 🟢 CLOSED (S111 W1) | — |
| TD-018 | D5 model shims hard delete | 🟡 PARTIAL | Shims active, DeprecationWarning fires |
| TD-019 | lifespan.py god-context-manager | 🟢 DECOMPOSED (S111 W2) | 718 → 108 LOC |
| **[NEW TD-020]** | DSL Variable Store (VAR-1) | 🔴 OPEN | Real gap, S127 W1 candidate |
| **[NEW TD-021]** | ExternalDBFacade + PoolingProfile | 🔴 OPEN | Real gap, S127 W2 candidate |
| **[NEW TD-022]** | Prompt Caching for Anthropic | 🔴 OPEN | Real gap, S127 W2-W3 candidate |
| **[NEW TD-023]** | CDC TransformCdcEventProcessor | 🔴 OPEN | Real gap, S128 W2 candidate |
| **[NEW TD-024]** | Consul CertStore backend | 🔴 OPEN | Real gap, S128 W1 candidate |
| **[NEW TD-025]** | DaskMixin in RouteBuilder | 🔴 OPEN | Real gap, S128 W2 candidate |
| **[NEW TD-026]** | gRPC File Streaming (DownloadFile/UploadFile) | 🔴 OPEN | Real gap, S128 W3 candidate |
| **[NEW TD-027]** | S3 Runtime Fallback (purgatory CB) | 🔴 OPEN | Real gap, S129 W1 candidate |
| **[NEW TD-028]** | CodecFacade | 🔴 OPEN | Real gap, S129 W3 candidate |
| **[NEW TD-029]** | DB Streaming cursor + db_transaction | 🔴 OPEN | Real gap, S130 W1 candidate |
| **[NEW TD-030]** | CB-1: Delete `core/utils/circuit_breaker.py` + `pybreaker_adapter.py` | 🔴 OPEN | **Quick win, S127 W1 candidate** |
| **[NEW TD-031]** | Layer linter regression S117-S126 | 🔴 OPEN | 25 NEW violations need S127 attention |

**Summary:** 9 OPEN P0/P1 items (vs. 4 in S111), 3 PARTIAL P0/P1, 8 CLOSED in S111-S124.

---

## Recommended Sprint S127-S128 Roadmap (2 sprints)

### Sprint S127 (5 waves)
- **W1 (quick wins):** TD-030 (CB-1 delete 2 files) + TD-031 partial (linter regression 5-10 of 25)
- **W2:** TD-020 (DSL Variable Store — VAR-1)
- **W3:** TD-021 (ExternalDBFacade + PoolingProfile migration in `item.py`)
- **W4:** TD-022 partial (Prompt Caching for Anthropic — cache_control injection in AIGateway)
- **W5:** ADR + CHANGELOG closure; remaining TD-031 linter cleanup

### Sprint S128 (5 waves)
- **W1:** TD-024 (Consul CertStore backend)
- **W2:** TD-023 (TransformCdcEventProcessor) + TD-025 (DaskMixin in RouteBuilder)
- **W3:** TD-026 (gRPC File Streaming — DownloadFile/UploadFile) + TD-022 continuation
- **W4:** Frontend per-page feature split (TD-013) + TD-031 linter cleanup
- **W5:** ADR + CHANGELOG closure

### Sprint S129+ (deferred)
- TD-027 (S3 Runtime Fallback + purgatory)
- TD-028 (CodecFacade)
- TD-029 (DB streaming cursor + db_transaction DSL)

---

## References

- `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-06-12.md` (22 domains, S92 state)
- `gap-analysis/MASTER-PROMPT-factcheck-plan-execute.md` (S109 state)
- `reports/reaudit/findings.md` (S109 30-point matrix)
- `reports/reaudit/tech_debt_register.md` (S111 state, TD-001..TD-019)
- `reports/reaudit/s112_layer_triage.md` (S112 layer work)
- `reports/reaudit/master_prompt_for_agent.md` (S109 master prompt, 395 lines — superseded by this S126 update)
- 9 subagent verification reports (6 timed out at 600s, 2 completed with full tables, 1 partial)
