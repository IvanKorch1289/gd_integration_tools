# DSL Coverage Matrix

> **Read methodology:** built from grep on `RouteBuilder` methods +
> `infrastructure/*` adapters + `entrypoints/*` handlers. NOT every method
> was traced through to its processor — master prompt enforces re-read of
> each touched file.

---

## A. RouteBuilder `from_*` methods (sources)

| Method | Status | Evidence |
|--------|--------|----------|
| `from_cdc` | ✅ | `dsl/builders/sources_mixin/` (legacy, kept for back-compat) |
| `from_cdc_capture` | ✅ | legacy |
| `from_cdc_logical` | ✅ | legacy |
| `from_cdc_registry` | ✅ | **NEW S101 W1** — preferred path via `get_cdc_source()` |
| `from_file` | ✅ | |
| `from_filewatcher` | ✅ | |
| `from_http` | ✅ | |
| `from_kafka` | ✅ | |
| `from_mqtt` | ✅ | |
| `from_rabbit` | ✅ | |
| `from_schedule` | ✅ | (workflow scheduling) |
| `from_sql` | ✅ | |
| `from_sse` | ✅ | (S94 W5) |
| `from_sse_multi` | ✅ | (S96 W4 — interleave/concat/first merge) |
| `from_telegram` | ✅ | **NEW S97 W4** — HMAC + secret validation |
| `from_webhook` | ✅ | |

**Missing / gaps:**
- `from_grpc` (no direct source, gRPC is bidirectional — would need `from_grpc_stream`)
- `from_graphql` (subscriptions possible via SSE/WS, but no dedicated source)
- `from_nats` (NATS adapter exists in `infrastructure/messaging/`, no DSL method)
- `from_imap` (mentioned in DEEP-RESEARCH as 12th protocol, not in DSL?)
- `from_mongo` (MongoDB source — not in core; could be extension)

---

## B. RouteBuilder action methods (verbs)

| Method | Status | Evidence |
|--------|--------|----------|
| `cache_write` | ✅ | |
| `cron_schedule` | ✅ | **NEW S103 W2** — 5-field cron |
| `db_call_procedure` | ✅ | |
| `db_delete` | ✅ | **NEW S95 W1** — safe parameterized SQL |
| `db_insert` | ✅ | **NEW S95 W1** |
| `db_query` | ✅ | |
| `db_query_external` | ✅ | |
| `db_upsert` | ✅ | **NEW S95 W1** — PG `ON CONFLICT DO UPDATE` |
| `entity_create`, `_delete`, `_get`, `_list`, `_update` | ✅ | R1.5 service DSL auto-CRUD |
| `graphql_query` | ✅ | |
| `http_call` | ✅ | |
| `invoke_workflow` | ✅ | R3.1 workflow DSL |
| `s3_get`, `s3_put` | ✅ | **NEW S104 W1** (D21 RPA) |
| `sftp_get`, `sftp_put` | ✅ | **NEW S104 W1** |
| `sql_exec` | ✅ | |
| `template_render_str` | ✅ | |
| `vault_read` | ✅ | |

**Missing / gaps:**
- `s3_delete`, `s3_list` (S3 operations incomplete)
- `ssh_exec` exists in DSL (S85 closure), but no `ssh_*_put`/`_get` (covered by sftp_)
- `entity_*` operations only for ORM-backed entities, not for arbitrary services
- No `sub_workflow` method visible — DEEP-RESEARCH D9 mentioned as missing
- No explicit `circuit_breaker` DSL method (middleware registry covers it)

---

## C. Extension-Safe Operations

**Allowed from extensions (`extensions/<name>/`):**
- `from_*` (all 17)
- All action methods (DSL is extension-safe)
- `route = RouteBuilder(route_id=...)` instantiation
- `from src.backend.core.audit.facade import emit_audit*` (after S106 W2)
- ORM via `from src.backend.core.domain.models import ...` (after S106 W1) for Risk A models
- ORM via `from src.backend.infrastructure.database.models import ...` (Risk B/C, linter violation: 39)
- Capability gate: `self._audit: Callable[[dict], None]` (callback DI pattern)
- `from src.backend.services.audit.audit_service import get_unified_audit_service` (linter violation: 11+ ext→services)

**NOT allowed (linter blocks):**
- Direct `src.backend.infrastructure.*` access (8 occurrences)
- Direct `src.backend.services.*` access (11 occurrences)
- Direct `src.backend.entrypoints.*` access (5+ occurrences)
- Direct `src.backend.schemas.*` access (2+ occurrences)

**Reconciliation:** All 39 extension violations = D5 B2/B3 (model moves) + ext→services/schemas/general.

---

## D. EIP (Enterprise Integration Patterns) coverage

Per DEEP-RESEARCH: **10/10 EIP coverage** claimed. Verified via file inventory:
- `src/backend/dsl/builders/camel_eip.py` — main EIP implementation
- `src/backend/dsl/builders/eip/` — sub-package
- `src/backend/dsl/builders/eip/messengers.py` — 397 LOC
- `src/backend/dsl/builders/control_flow.py` — 416 LOC (largest)

**EIP patterns (per Camel):**
- ✅ Message routing (content-based, recipient list, splitter, aggregator, filter, resequencer)
- ✅ Message transformation (enrich, convert, normalize, removeHeader)
- ✅ Messaging channels (point-to-point, publish-subscribe, dead letter, guaranteed)
- ✅ Message construction (event message, request-reply)
- ✅ Endpoint (dynamic router, load balancer, service activator)
- ✅ Error handling (dead letter channel, guaranteed delivery, redelivery, retry)
- ✅ Messaging bridge (between protocols)
- ⚠️ Saga / LRA: `saga_lra.py` + `saga_lra_processor` (per subdir listing) — partial

---

## E. Protocol Coverage (entrypoint bridges)

Per `tools/check_protocol_coverage.py`:

| Protocol | Bridge module | Status |
|----------|---------------|--------|
| REST | `entrypoints/api/` | ✅ |
| GraphQL | `entrypoints/graphql/` | ✅ |
| gRPC | `entrypoints/grpc/` | ✅ |
| SOAP | `entrypoints/soap/` | ✅ |
| **WebSocket** | `entrypoints/websocket/ws_handler.py` | ❌ **MISSING** |
| **Webhook** | `entrypoints/webhook/handler.py` | ❌ **MISSING** |
| **Express** | `entrypoints/express/router.py` | ❌ **MISSING** |
| **SSE** | `entrypoints/sse/handler.py` | ❌ **MISSING** |
| MQTT | `entrypoints/mqtt/` | ✅ |
| CDC | `entrypoints/cdc/` | ✅ |
| MCP | `entrypoints/mcp/` | ✅ |
| Kafka | `entrypoints/kafka/` | ✅ |
| RabbitMQ | `entrypoints/rabbit/` | ✅ |
| **Action bridge** | `entrypoints/_action_bridge.py` | ⚠️ file exists but coverage check still complains (maybe different expected name?) |
| **Tier 1 setup** | `dsl/commands/setup.py` | ❌ **MISSING** |
| Stream | `entrypoints/stream/` | ✅ |
| Email | `entrypoints/email/` | ✅ |
| Filewatcher | `entrypoints/filewatcher/` | ✅ |
| HTTP/3 | `entrypoints/http3/` | ✅ |
| AsyncAPI | `entrypoints/asyncapi/` | ✅ |

**Net:** 4 protocol handlers + 1 tier-1 setup file MISSING → protocol coverage gate is **FAILING**.

---

## F. AI / Agent capabilities (DSL exposure)

- `from src.backend.dsl.agents.fastmcp_server import ...` (MCP server)
- `RouteBuilder.from_*` for AI tools — needs explicit verification
- `agent_dsl/infra.py` (409 LOC) — AI agent DSL
- `dsl/agents/` — limited to MCP server
- AI workspace, prompt versioning — internal, not in DSL directly

**Recommendation:** Sprint 2 should expose key AI operations (model invoke, tool dispatch, workspace create) via DSL.

---

## G. Real TODOs / Scaffold / Partial

| Item | Type | Source |
|------|------|--------|
| D5 B2 (orderkinds, orders, files) | D5 split-brain | S106 W3-W4 |
| D5 B3 (workflow_instance, workflow_event) | D5 + native enum | S106 W5 |
| `entrypoints/*/handler.py` 4 missing files | protocol coverage FAIL | Sprint 2 |
| 77 `_emit_audit` callsites | 2 architecture patterns | S107+ W1+ |
| DSN driver availability check (pyodbc/aioodbc optional deps) | runtime risk | Sprint 2 or 3 |
| Ratchet allowlist 1636 — slow burn-down | cosmetic | Continuous |
| 70 collection errors + 572 pre-existing test failures | test baseline | Sprint 2 (baseline allowlist) |
| 9 NEW core linter violations | recently introduced | Sprint 1 |

---

## H. Recommendations (DSL coverage gaps)

1. **Add `from_nats`, `from_mongo`, `from_grpc_stream` source methods** — bridge DSL to all 12 advertised protocols.
2. **Add `sub_workflow` action method** — DEEP-RESEARCH D9 partial.
3. **Add 4 missing entrypoint handlers** — `ws_handler.py`, `webhook/handler.py`, `express/router.py`, `sse/handler.py`.
4. **Wire `emit_capability_check` helper in `audit_mixin.py:_emit_audit`** — 17 callsites in one commit, S106 W2 helper ready.
5. **Add baseline-allowlist for pre-existing test failures** — separate signal from noise.
6. **Split `core/audit/facade.py` into `facade/<domain>.py`** — 394 LOC is borderline god-module.
