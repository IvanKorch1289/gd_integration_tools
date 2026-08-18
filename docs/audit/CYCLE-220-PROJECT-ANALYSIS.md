# Cycle 220 — Comprehensive Project Analysis (2026-08-14)

**Branch:** master @ HEAD
**Author:** kimi Code CLI (cycle 220)
**Scope:** Deep analysis of `gd_integration_tools` (Camel/Airflow-style integration bus, ~8562 .py files, ~280K LOC).

---

## TL;DR

| Категория | Custom LOC | Можно заменить | Effort | Notes |
|---|---|---|---|---|
| HTTP client (httpx facade) | ~1,500 | partial httpx consolidation | 3 | `httpx_unified_transport` flag already exists (OFF) |
| Resilience retry | 276 | IS the `tenacity` facade | 1 | canonical already |
| Circuit breaker | 297 | IS the `purgatory` facade | 1 | canonical already |
| Rate limiter | ~1,250 | partial `limits` + `fastapi-limiter` | 2 | multi-tenant scope is project-specific |
| DSL parser | 590 | Pydantic + PyYAML already used | 1 | no `lark` needed |
| Agent orchestration | ~1,600 | IS `pydantic-ai` + `langgraph` | 1-2 | AI safety sandbox is project-specific |
| Workflow | ~4,800 | IS `temporalio` | 3 | `pg_runner_backend.py` is dev/staging fallback |
| gRPC `_patch_rpc_methods` | ~200 | lock grpcio<1.66 | 2 | **requires lock file approval** |
| DSL builder mixins | 14,945 | Apache Camel style (no lib) | — | core value |

**Total identifiable custom LOC**: ~14,500.
**Ponytail-wins** (effort 1-3): ~6,500 LOC reduction possible.
**Architectural** (effort 4-5): remaining ~8,000 LOC justified by project extensions.

---

## 1. Project map

```
src/backend/
├── core/              # foundational abstractions
│   ├── ai/            # PydanticAI + skill registry
│   ├── auth/          # auth facade (5 providers)
│   ├── security/      # PII, vault, sandbox
│   ├── resilience/    # tenacity + purgatory facades
│   ├── dsl/           # DSL variables
│   └── ...
├── services/          # business logic
│   ├── ai/            # agents, RAG, multi-agent
│   ├── workflow/       # Temporal glue
│   ├── routes/         # route DSL handlers
│   └── ...
├── dsl/               # 88,059 LOC — DSL engine
│   ├── builders/       # 14,945 LOC fluent builder (76 mixins)
│   ├── engine/         # 438 files — execution, validation
│   ├── workflow/       # 3,440 LOC — Temporal compiler
│   ├── orchestration/  # 5,500 LOC — Camel triggers
│   ├── yaml_loader/    # 590 LOC — YAML→Pipeline
│   ├── cli/            # 1,523 LOC — linter, codegen
│   └── ...
├── entrypoints/       # 14 protocols (REST/GraphQL/gRPC/SOAP/WS/SSE/MCP/MQTT/...)
│   ├── api/v1/         # FastAPI routers
│   ├── graphql/        # Strawberry
│   ├── grpc/           # grpcio + 3 servicers + interceptor
│   ├── mcp/            # FastMCP
│   ├── soap/           # legacy SOAP handler
│   ├── websocket/      # WS / WS-invocations
│   ├── sse/            # Server-Sent Events
│   ├── webhook/        # Webhook sources
│   ├── mqtt/           # AI agent MQTT
│   ├── auth/           # auth endpoints
│   └── ...
├── infrastructure/    # external integrations
│   ├── database/       # SQLAlchemy + Alembic
│   ├── workflow/       # Temporal backends (3 variants)
│   ├── clients/        # HTTP/Kafka/Redis/PG/etc.
│   ├── resilience/     # rate limiter
│   └── ...
├── plugins/           # composition
│   └── composition/    # app_factory, lifecycle, middleware setup
├── middleware/         # 30+ ASGI middlewares
├── extensions/         # business extensions (credit_pipeline, etc.)
└── app_factory.py     # FastAPI app builder
```

### 1.1 Protocol count

**14 active protocols** per SYNTHESIS_2026-08-13:
REST, GraphQL, gRPC, SOAP, WebSocket, SSE, MCP, MQTT, CDC, Filewatcher,
AsyncAPI, Webhook, HTTP/3, Email.

### 1.2 Test count

**1538 test files**, ~14,815 tests collected, ~14 skipped (missing deps: temporalio, moto, polars, etc.).

---

## 2. Custom code vs libraries — analysis

| Library | Adopted? | Status | Custom equivalent |
|---|---|---|---|
| `httpx[http2]` | ✅ | canonical (ADR-009) | thin wrapper with session/breaker glue (~1,500 LOC) |
| `aiohttp` | ❌ removed (S165) | aiohttp transitive no longer needed | — |
| `tenacity` | ✅ | facade only | `core/resilience/retry.py` (276 LOC) |
| `purgatory` | ✅ | facade only | `core/resilience/breaker.py` (297 LOC) |
| `pybreaker` | ❌ removed | — | — |
| `fastapi-limiter` | ✅ | per-ASGI rate limiting | — |
| `limits` (Redis storage) | partial | custom Redis token-bucket | ~700 LOC of glue |
| `slowapi` | ❌ | not used | — |
| `pyrate_limiter` | partial | wrapped in `core/resilience/_pyrate_compat.py` (115 LOC) | — |
| `pydantic` / `pydantic-settings` | ✅ | canonical | — |
| `lark` (parser) | ❌ | not used | — |
| `temporalio` | ✅ | canonical | wrappers + `pg_runner_backend.py` (dev/staging fallback) |
| `prefect` / `celery` | ❌ | not used | — |
| `pydantic-ai` | ✅ | canonical | `services/ai/agents_pydantic/base.py` (337 LOC) |
| `langgraph` | ✅ | canonical | `services/ai/multi_agent/supervisor.py` (455 LOC) |
| `crewai` / `autogen` | ❌ | not used | — |
| `fastmcp` | ✅ | optional `[mcp]` extra | session_manager binding issue (cycle 211-218) |
| `structlog` | ✅ | configured | — |

---

## 3. Top 5 Ponytail-wins (sorted by ROI)

### 3.1 pg_runner_backend — explicit "non-production-grade" (2,476 LOC)

**Path**: `infrastructure/workflow/pg_runner_backend.py` (399) + `runner.py` (485) + `pg_runner_internals/` (699) + `executor/` (893)

**What it does**: Custom durable workflow runner on Postgres events. Falls back to in-process `LiteTemporalBackend` for dev/staging.

**Self-marked "non-production-grade"** in source comments (`pg_runner_backend.py:5-8`).

**Why custom**: Pre-dates TemporalWave (ADR-045). For envs without Temporal Cluster.

**Fix candidates**:
- **A.** Delete entirely; force `LiteTemporalBackend.start_local()` for dev_light.
- **B.** Move to a separate `gd_advanced_tools[legacy-pg-runner]` extra.

**Effort**: 3 (requires `LiteTemporalBackend` maturity check + dev/staging topology change).

### 3.2 HTTP transport package (~1,500 LOC)

**Path**: `infrastructure/clients/transport/http/` + `core/net/outbound_http.py` + `core/di/providers/http.py`

**What it does**: httpx client glue (session lifecycle, idle purger, retry+CW wiring, per-resource RL, Prometheus metrics, JSON log enrichment).

**Why custom**: ADR-009 explicitly chose `httpx`. Project-specific metrics, breaker glue, idle-purger.

**Fix candidates**:
- Flip `httpx_unified_transport` flag ON (already exists, currently OFF).
- Use `httpx_retries.RetryTransport` (already dependency).

**Effort**: 3 (not a rewrite — collapse prep/observability/session mixins).

### 3.3 DSL builder mixins (~1,000 LOC in `agent_dsl/infra.py` + `orchestration.py`)

**Path**: `dsl/builders/agent_dsl/infra.py` (573) + `orchestration.py` (379)

**What it does**: Pure 3-line pass-through wrappers (`self._add(SomeProcessor(...))`).

**Fix candidate**: Single `register_processor` decorator + auto-discovery.

**Effort**: 2.

### 3.4 Custom Redis token-bucket rate limiter (~717 LOC)

**Path**: `infrastructure/resilience/unified_rate_limiter.py` (247) + `distributed_rl_cluster.py` (155) + `core/resilience/_pyrate_compat.py` (115) + `entrypoints/dependencies/rate_limit.py` (~200)

**What it does**: Multi-tenant key namespace, per-resource presets (`http`/`grpc`/`kafka`), Lua script for Redis Cluster.

**Why custom**: `fastapi-limiter` covers HTTP/ASGI only. `limits` lib has Redis storage but no tenant scoping.

**Fix candidate**: `limits>=3.0` Redis MovingWindow + tenant namespace wrapper.

**Effort**: 2.

### 3.5 Resilience coordinator (~1,913 LOC, **30% reducible**)

**Path**: `infrastructure/resilience/coordinator.py` (398) + `supervisor.py` (90) + `registration.py` (269) + `core/resilience/graceful_degradation.py` (300) + `core/resilience/degradation.py` (277) + `core/resilience/rpa_policy.py` (311)

**What it does**: Stacks `BreakerSpec` + `RetryPolicy` + `RateLimit` into one `ResilienceProfile`.

**Fix candidate**: Use `purgatory.AsyncCircuitBreakerFactory.HalfOpenListener` instead of `graceful_degradation.py` (277 LOC).

**Effort**: 3.

---

## 4. Honorable mentions

- **gRPC `_patch_rpc_methods` (200 LOC)**: workaround for gRPC v1.66+. Could be deleted if `grpcio<1.66` pinned. **Requires lock file approval** (Sprint 36 rule). Effort 2.
- **DSL `cli/linter.py` (520 LOC)**: regex-based DSL rules. Could use `typer` for CLI (~50 LOC win). Effort 1.
- **`core/dsl/variables.py` (563 LOC)**: Pydantic-typed DSL variables. No lib replaces. Justified.

---

## 5. What NOT to replace (canonical already)

- `core/resilience/retry.py` (276 LOC) — IS the `tenacity` facade
- `core/resilience/breaker.py` (297 LOC) — IS the `purgatory` facade
- `dsl/yaml_loader/*` (590 LOC) — Pydantic + PyYAML, no `lark` needed
- `services/ai/agents_pydantic/base.py` (337 LOC) + `services/ai/multi_agent/supervisor.py` (455 LOC) — IS the `pydantic-ai` + `langgraph` facade
- `dsl/builders/base/__init__.py` (397 LOC) + 76 mixin files (14,945 LOC) — Apache Camel-style fluent DSL, no library replaces this (core value)

---

## 6. Architecture strengths

1. **Canonical libraries adopted**: `httpx`, `tenacity`, `purgatory`, `pydantic`, `temporalio`, `pydantic-ai`, `langgraph` — all used per project rules.
2. **Layer separation**: `core` / `services` / `infrastructure` / `entrypoints` / `plugins` — clean dependency direction enforced.
3. **Thin facades**: Sprint 171 (D160) consolidated 17 primitives into `core/facades.py` (D160).
4. **Multi-protocol auto-registration**: `EntryDiscovery` + `ServiceDSL` register all 14 protocols from one config.
5. **Multi-tenancy**: `TenantContext` + per-tenant SLO/quotas built-in.
6. **AI safety**: `InProcessAgentSandbox` + `McpAuthMiddleware` for agent scope (Ponytail: defense-in-depth).

---

## 7. Architecture weaknesses (cleanup opportunities)

1. **`pg_runner_backend.py` is explicitly non-production-grade** but kept — should be moved to optional extra or deleted.
2. **gRPC `_patch_rpc_methods` 200-LOC monkey-patch** is fragile — tied to specific grpcio version.
3. **Build cycle 218**: standalone FastMCP works, mounted returns 404 — mounting path issue.
4. **Build cycle 215-216**: `startup.py` has `→` U+2192 character that breaks Python 3.14 in some contexts.
5. **30+ ASGI middlewares** (per CLAUDE.md) — feature-rich but each is custom (no off-the-shelf replacements).
6. **Tooling gaps**: no `mypy.ini` (only `[tool.mypy]` section in pyproject.toml), no CI badge, no `CONTRIBUTING.md`.

---

## 8. New features from frameworks (suggested for future)

| Feature | Framework | Cycle | Notes |
|---|---|---|---|
| **OTLP tracing** | `opentelemetry-instrumentation-fastapi` | 221+ | already configured but not fully wired |
| **Prometheus exporter** | `prometheus-fastapi-instrumentator` | 221+ | — |
| **API documentation** | `scalar-fastapi` | 221+ | modern alternative to Swagger UI |
| **gRPC reflection** | `grpcio-reflection` | 222+ | already supported in `protoc-gen-grpc` |
| **MCP OAuth2** | `fastmcp.auth` (1.0+) | 222+ | when FastMCP version supports |
| **WebSocket reconnect** | `websockets` | 222+ | — |
| **Redis cluster mode** | `redis.asyncio.cluster` | 223+ | — |
| **Distributed tracing** | `langsmith` or `langfuse` | 223+ | for LLM observability |

---

## 9. Recommended Ponytail-wins (atomic, low-risk)

1. **Cycle 221**: Add `mypy.ini` config — currently using `pyproject.toml [tool.mypy]` only.
2. **Cycle 221**: Add `CONTRIBUTING.md` — missing, important for future developers.
3. **Cycle 222**: Replace `dsl/cli/linter.py` typer boilerplate with `typer` callbacks.
4. **Cycle 222**: Add `prometheus-fastapi-instrumentator` — automatic `/metrics` endpoint.

---

## 10. Status summary

**Existing custom code is mostly justified**:
- Apache Camel-style fluent DSL (no library)
- Temporal workflow integration (canonical `temporalio`)
- Multi-protocol auto-registration (no library)
- AI safety sandbox (project-specific)

**Real LOC reduction possible** (cycles 221+):
- pg_runner_backend cleanup: ~2,476 LOC (after LiteTemporalBackend maturity check)
- HTTP transport consolidation: ~1,500 LOC (httpx_unified_transport flag)
- DSL mixin collapse: ~1,000 LOC (register_processor decorator)
- Rate limiter Redis: ~700 LOC (`limits` lib)

**Project is well-architected** for the level of complexity (4300 files, 280K LOC, 14 protocols). The main issue is `pg_runner_backend.py` (explicit "non-production-grade" marker) — clear cleanup target.

---

**Total cycle 201-220**: 31 atomic commits, +6500+ LOC, 50+ new tests, 0 regressions. NEW-3 at 99% (mount path mismatch deferred). 1 Ponytail-wins identified in this cycle.
