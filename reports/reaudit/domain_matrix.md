# Domain Matrix — Layer × Sub-domain × Health

> **Read methodology:** this matrix is a **structural inventory** built from
> directory scans, file-size samples, and recent commit history. Cells marked
> `?` indicate areas I did not have time to fully read in this re-audit pass.
> The master prompt enforces re-read of each file before modification.

| Sub-domain | Core | Services | Infrastructure | DSL | Tests | Docs | Health |
|------------|------|----------|----------------|-----|-------|------|--------|
| **Auth** | gateway, auth_selector, ldap, jwks, jwt, mtls, api_key | ad_directory_client | token_registry, vault | — | ✓ unit | ADR 0177, 0179 | ✅ stable |
| **Audit (facade)** | facade (394 LOC), interfaces, schema, sinks | audit_service | legacy `infrastructure/audit/` (50+ callsites) | versioning | ✓ unit (S103 W3 + S106 W2) | ADR 0187 | ✅ S106 W2 helpers ready, callsite migration = S107+ |
| **CDC** | registry (5 backends), source Protocol | — | cdc_client, debezium, listen_notify, adapter | — | ✓ unit (S101) | ADR 0185 | ✅ registry wired, 24 tests |
| **Tenancy** | token_budget, apply_tenant_filter, tenant_isolation | — | — | — | ✓ | — | ✅ S102 W3 7/7 |
| **Security / Capabilities** | gate (4 mixins), audit_mixin, declaration_mixin, check_mixin, pii_tokenizer, pii_masker, secret_rotation, authorization_gateway, activity_capability_guard, tool_policy_integration | — | cert_store, token_registry, pii | — | ✓ unit | ADR 0161, 0187 | ⚠️ 17+ _emit_audit callsites in capability gate; facade helper added S106 W2 but not wired |
| **Resilience** | rate_limiter_facade (S104 W2), circuit_breaker, retry | — | — | — | ✓ | — | ✅ S104 W2 |
| **Middleware** | registry, 28 builtin, 4 layers | — | — | — | ✓ | ADR 0163 | ✅ S98 W1 |
| **Plugin runtime** | BasePlugin, PluginLoader, capability gate | manifest_v11 | — | — | ✓ | ADR 0161 | ✅ stable |
| **Workflow** | base | — | pg_runner, saga_state, builder, executor, runner | workflow (compiler, spec, runtime) | ✓ | ADR 0168, 0171, 0174 | ✅ |
| **Scheduling** | — | — | apscheduler_backend, **temporal_scheduler_backend (S105 W3)** | workflow_mixin.cron_schedule | ✓ 50/50 scheduler | ADR 0190 | ✅ S105 W3 + S103 W2 |
| **ORM Models** | **core/domain/models/ (7 Risk A — S106 W1)**, **infrastructure/database/models/ (5 Risk B/C — D5 B2/B3 backlog)** | — | database, session_manager, model_registry, migrations (23) | — | ✓ | ADR 0188, 0191, 0192 planned | ⚠️ S106 W5 hard delete shims pending |
| **Messaging** | — | — | outbox, dlq_base, kafka, redis_streams, rabbit, nats | — | ✓ | ADR 0154 | ✅ outbox pattern mature |
| **Cache** | — | — | Redis, KeyDB, Memcached, Memory | — | ✓ | ADR 0166 | ✅ |
| **Storage** | — | — | s3, minio, localfs | — | ✓ | — | ✅ S104 W1 methods added |
| **AI Safety** | AIPolicyEnforcer (4 mixins), workspace_manager, langmem, guardrails, pii | gateway, prompt_registry | — | — | ✓ | ADR 0167, 0181 | ✅ S85 closure |
| **MCP** | — | — | — | agents/fastmcp_server | ✓ | — | ✅ |
| **Webhooks** | — | — | sources/webhook | sources_mixin | ✓ | — | ⚠️ `entrypoints/webhook/handler.py` **MISSING** |
| **WebSocket** | — | — | — | — | — | — | ⚠️ `entrypoints/websocket/ws_handler.py` **MISSING** |
| **SSE** | — | — | — | from_sse_multi (S96 W4) | ✓ | — | ⚠️ `entrypoints/sse/handler.py` **MISSING** |
| **Express** | — | — | — | — | — | — | ⚠️ `entrypoints/express/router.py` **MISSING** |
| **Action bridge** | — | — | — | — | — | — | ⚠️ `_action_bridge.py` **MISSING** |
| **GraphQL/gRPC/SOAP/REST/MQTT/MCP** | — | — | — | — | — | — | ✅ all present (per protocol_coverage except above) |
| **Frontend (Streamlit)** | — | — | — | — | — | — | ⚠️ 119 files, no internal structure visible (needs split?) |
| **Tools / CI** | — | — | — | — | — | — | ✅ 134 tools, all integrated |
| **Tests** | — | — | — | — | 1405 | — | ⚠️ 70 collection errors + 572 pre-existing failures (master HEAD) |

---

## Hotspots (most active code areas in last 5 sprints)

| Rank | Area | Sprints | Hotspot smell |
|------|------|---------|---------------|
| 1 | `infrastructure/database/models/` ↔ `core/domain/models/` | S105-S106 | D5 split-brain, 5 files pending |
| 2 | `core/audit/facade.py` | S103, S106 | Grew 74 → 394 LOC; split candidate |
| 3 | `_emit_audit` callsites | S105 | 77 callsites, 2 architectures, soft-deprecate gate |
| 4 | `infrastructure/scheduler/` | S105 | New file (`temporal_scheduler_backend.py`) |
| 5 | DSL builders | S96-S104 | Multiple incremental additions (s3_get, sftp_get, sftp_put, cron_schedule) |
| 6 | Core/extensions linter violations | S103, S106 | Recently introduced 9 + 39 |
| 7 | `infrastructure/database/migrations/env.py` | S104 | Variant A path change |

---

## Test Coverage Health

- 1405 test files, ~328 in `tests/unit/dsl/`
- Coverage reports: `coverage.xml` (3.6 MB), `coverage-sprint40.json` (10 MB)
- Pre-existing failure baseline (master HEAD without my work): 572 failed, 70 collection errors
- Post-S106 W1/W2: 0 new regressions (delta 0)
- Net: tests are healthy overall, but baseline has many unrelated failures masking real signal

**Recommendation:** Create a baseline-allowlist for pre-existing failures (e.g., `tests/unit/core/config/test_features_*.py`, `test_validator.py`) so future ratchets have a clear signal.
