# File Inventory (per-domain)

> Read-time methodology: this inventory is a **summary** based on directory scans,
> file size sampling, and recent commit history. NOT every file was read in full —
> large directories (`src/backend/dsl/engine/processors/`, `src/backend/dsl/builders/`)
> were sampled. For full audit, the master prompt enforces re-read of each touched file.

---

## A. Source Code (`src/`)

### `src/backend/core/` (40+ sub-packages, ~580 files)

| Sub-package | Sample files | Notes |
|-------------|--------------|-------|
| `actions` | action_dispatcher, action_handler_registry | R1 Service Activator + 6 invoke modes |
| `ai` | context_strategy, gateway_pipeline_mixin, guardrails/, langmem_client | S101+S102 work area; 4-mixin AIPolicyEnforcer |
| `audit` | facade.py (394 LOC, was 74), interfaces.py, schema/, sinks/ | S103+S106 audit work |
| `auth` | auth_selector.py (S96 relocation), gateway.py (S95 W4 facade), ldap/, jwks_cache, jwt_blacklist, mtls_backend | Multi-method auth |
| `cdc` | registry.py (S101 W1), source.py Protocol, fake.py | CDC backend registry |
| `config` | base.py, settings.py, services/{cache,queue,storage,mail}.py, database.py (DSN), features/ | Multi-source config |
| `decorators` | timer, retry, etc. | |
| `di` | container.py, dependencies.py, providers/{ai,http,jupyter,security,...}.py | DI providers registry |
| `domain/models/` | (NEW S106 W1) base.py, cert.py, dsl_snapshot.py, langmem_models.py, outbox.py, rule_engine.py, users.py — all moved from `infrastructure/database/models/` | 7 Risk A files canonical |
| `enums` | database.py (mssql/mysql/db2 added S104 W3) | |
| `feature_flags` | flags, validator | |
| `interfaces` | db_model.py, batch_capable.py, ratelimit_gateway.py | Protocols |
| `logging` | facade (replaces stdlib logging) | |
| `messaging` | — | |
| `middleware` | registry, 28 builtin middlewares, 4 layers order 0-999 | S98 closure |
| `models` | (empty? or refactored to domain) | Was the old home for ORM |
| `net` | outbound_http.py (WAF) | S85 closure |
| `observability` | metrics, tracing | |
| `orchestration` | — | |
| `plugin_runtime` | BasePlugin, PluginLoader, capability gate | |
| `protocols.py`, `svcs_registry.py`, `providers_registry.py` | Service registry | |
| `repositories` | base/, orders/, orderkinds/, outbox/, rule_engine_repository, users/ | |
| `request_context.py` | | |
| `resilience` | rate_limiter_facade (S104 W2), snapshot_job.py | |
| `scaling` | | |
| `secrets_sources.py` | Vault | |
| `security` | auth, capabilities/gate/{audit,check,declaration}_mixin.py, secret_rotation, pii_tokenizer, authorization_gateway/, pii_masker, tool_policy_integration | 17 _emit_audit callsites в capability gate alone |
| `serialization` | | |
| `state` | | |
| `tenancy` | token_budget, tenant_isolation, apply_tenant_filter (S88 W2) | |
| `types` | | |
| `util` | | |
| `utils` | circuit_breaker | |
| `workflow` | | |

### `src/backend/dsl/` (26 sub-packages, ~200 files)

| Sub-package | Sample | Notes |
|-------------|--------|-------|
| `adapters/` | | |
| `agents/` | fastmcp_server.py | MCP |
| `analysis/` | | |
| `blueprints/` | blueprint_loader.py, 10 patterns R2 | |
| `builders/` | **37 files** including route.py (16 069 LOC total), integration.py, integration_group_a/b.py, infrastructure_dsl.py (S104 W1 RPA methods), sources_mixin/, integration_core/workflow_mixin.py (cron_schedule S103 W2) | Camel-style fluent DSL |
| `cli/` | generate.py (S99 W1 TODO closed) | |
| `codec/` | json.py | |
| `commands/` | | |
| `contracts/` | | |
| `di/` | container.py | |
| `engine/` | context.py, exchange.py, processors/ (17069 LOC total), versioning.py, state.py, search.py, transforms/, registry/ | Largest directory |
| `helpers/` | | |
| `integration_gateway/` | | |
| `loaders/` | | |
| `models/` | | |
| `orchestration/` | | |
| `preprocess/` | | |
| `processors/` | batch_processor, data_lineage, event_store/, idp_pipeline_processor, plan_execute_processor, reflection_loop_processor, router_specialist_processor, saga_lra_processor, strangler_fig | |
| `registry/` | processor.py, errors.py | `@processor` decorator |
| `search/` | | |
| `service/` | | |
| `transforms/` | | |
| `versioning/` | audit_versioning.py | S58 W1 |
| `workflow/` | builder, compiler/, spec/ (AgentInvokeDeclaration, MemoryScope), runtime/ | Temporal workflow DSL |
| `yaml_loader/` | | |

### `src/backend/infrastructure/` (30+ sub-packages)

| Sub-package | Notes |
|-------------|-------|
| `ai/` | langmem_models.py (S101/S105 shim consumer) |
| `antivirus/` | ClamAV |
| `application/` | |
| `audit/` | Legacy _emit_audit callsites (50+) |
| `cache/` | Redis/KeyDB/Memcached |
| `cdc/` | cdc_client_adapter, debezium, listen_notify |
| `chaos/` | |
| `clients/` | storage (vector_store), transport (http_httpx, request_mixin), external/ (logger) |
| `database/` | **models/ (still has 5 files: orders, orderkinds, files, workflow_event, workflow_instance)**, migrations/ (23 versions), session_manager, model_registry, database.py |
| `eventing/` | |
| `execution/` | dask_backend |
| `external_apis/` | logging_service (deprecated) |
| `import_gateway/` | |
| `logging/` | (allowed stdlib) |
| `messaging/` | dlq_base, outbox, kafka/redis/rabbit/nats |
| `monitoring/` | |
| `notifications/` | |
| `observability/` | structlog_batching (allowed stdlib) |
| `persistence/` | mssql/mysql/db2 (S104 W3) |
| `policy/` | |
| `repositories/` | base/, orders/, orderkinds/, outbox/, rule_engine_repository, users/ |
| `resilience/` | |
| `scheduler/` | apscheduler_backend.py, **temporal_scheduler_backend.py (NEW S105 W3)** |
| `secrets/` | vault, token_registry |
| `security/` | cert_store, token_registry, pii |
| `sinks/` | |
| `sources/` | telegram_webhook (S97 W4), webhook, file, queue |
| `storage/` | s3, minio, localfs |
| `watermark/` | |
| `workflow/` | pg_runner_*, saga_state, builder, executor, runner |

### `src/backend/entrypoints/` (12+ sub-packages)

| Sub-package | Notes |
|-------------|-------|
| `api/` | FastAPI routes |
| `auth/` | |
| `base/` | |
| `cdc/` | |
| `cli/` | |
| `graphql/` | |
| `grpc/` | |
| `health/` | |
| `kafka/` | |
| `mcp/` | FastMCP |
| `mqtt/` | |
| `rabbit/` | |
| `rest/` | |
| `soap/` | |
| `sse/` | (handler.py **missing** per check_protocol_coverage) |
| `webhook/` | (handler.py **missing**) |
| `websocket/` | (ws_handler.py **missing**) |
| `express/` | (router.py **missing**) |
| `_action_bridge.py` | (**missing** — protocol coverage FAIL) |

### `src/backend/services/`, `schemas/`, `workflows/`, `utilities/`, `ai/`, `ops/`, `plugins/`

Standard layer structure. Notable: `services/audit/audit_service.py` (S103 W3 facade source), `workflows/worker.py` (S105 W3 Temporal real).

---

## B. Frontend (`src/frontend/`)

- `streamlit_app/` — 119 Python files (Streamlit pages)
- `public/` — static assets

---

## C. Tests (`tests/`)

| Subdir | Files | Marker |
|--------|-------|--------|
| `unit/` | 1281 | `@pytest.mark.unit` |
| `integration/` | 40 | `@pytest.mark.integration` |
| `e2e/`, `chaos/`, `perf/` | smaller | |
| `testkit/` | 84 | testkit utilities (auth_fixtures, cassettes, fixtures, etc.) |
| `extensions/*/tests/` | — | per-extension |

**DSL test coverage (sample):**
- `tests/unit/dsl/` — 328 files
- 70 collection errors (pre-existing, unrelated to recent work)

---

## D. Tools (`tools/`)

134 Python files. Categories:
- Linters: `check_layers.py`, `check_docstrings.py`, `check_audit_deprecation.py`, `check_auth_coverage.py`, `check_compat.py`, `check_fallback_matrix.py`, `check_feature_flags.py`, `check_layer_imports.py`, `check_mcp_export.py`, `check_plugin_system.py`, `check_protocol_coverage.py`, `check_side_effects.py`, `check_streamlit_security.py`, `check_team_ownership.py`, `check_v11_artefacts.py`, `check_waf_coverage.py`
- Codemods: `fix_except_bug.py`, `add_docstrings.py`, `audit_silent_excepts.py`
- Reporting: `audit_stdlib_logging.py`, `coverage_gate.py`, `protocol_coverage.py`
- ADRs: `build_adr_index.py`, `build_adr_wiki.py`
- Build: `changelog_autogen.py`, `env_example.py`
- API: `api_fuzz_runner.py`

---

## E. Extensions (`extensions/`)

| Plugin | Files | Notes |
|--------|-------|-------|
| `core_entities/users/` | 4 (domain, repositories, services, tests) | Risk A — migrated S106 W1 |
| `core_entities/orders/` | 4 | Risk B — pending D5 B2 |
| `core_entities/orderkinds/` | 2 | Risk B — pending D5 B2 |
| `core_entities/files/` | 4+ | Risk B (via OrderFile) — pending D5 B2 |
| `credit_pipeline/` | 5+ | Linter violations (workflows, services) |
| `example_plugin/`, `test_plug/` | scaffold | Reference plugins |

---

## F. Documentation (`docs/`)

| Subdir | Count | Notes |
|--------|-------|-------|
| `adr/0*.md` | 140 | 0175-0190 active (S93-S106) |
| `cookbooks/` | 6 | 01-ai-agent-tools-whitelist, 02-outbox-multi-instance-claim, 03-e2b-jupyter-sandbox, 04-circuit-breaker-middleware, 05-pool-health-monitoring |
| `tutorials/` | 18 | 00-08 walkthroughs |
| `how-to/` | 5 | add_processor, chaos, perf, sign_release |
| `architecture/`, `api/`, `bpmn/`, `analysis/`, `config/`, `deployment/`, `dsl/`, `explanation/` | various | |

---

## G. Config

- `config/vocabularies/` — domain vocabularies
- `config_profiles/dev.yml` — dev profile (contains `ssl_mode: "prefer"` per S104 W3 root-cause)
- `alembic.ini`, `pyproject.toml`, `uv.lock`

---

## H. Other

- `deploy/helm/`, `deploy/k8s/`, `deploy/windows-worker/` — deployment manifests
- `dashboards/` — Grafana dashboards
- `artifacts/sbom/`, `artifacts/ragas/` — CI artifacts
- `graphify-out/` — code graph
- `analysis/v2/` — V2 gap analyses
- `kimi-export-session_-20260611-104055.md` — Kimi session log
- `Makefile` (109 lines) + `make/*.mk` (16 split files)
- `Makefile.security` — security target overrides
- `manage.py` — Django-style management
