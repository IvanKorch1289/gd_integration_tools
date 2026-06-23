# Deep Repository Audit — Technical Report & Refactoring Plan

**Date**: 2026-06-22 (Session audit)
**Auditor**: Principal Software Architect + Code Auditor
**Scope**: Full repository (3,888+ Python files)
**Session**: Horizon 1 (P1-P5, P8-P9) COMPLETED, Horizon 2 in progress

---

## A. EXECUTIVE SUMMARY

### 10–20 Key Findings

1. **CRITICAL: InProcessAgentSandbox zero isolation (default)** — `agent_sandbox.py:85` — DEFAULT sandbox runs agent code directly in process memory
2. **CRITICAL: Tool whitelist enforced on wrong target** — `gateway_orchestrator_mixin.py:84` — checks `workflow_id` instead of actual tool being invoked
3. **CRITICAL: Module whitelist bypass in SkillRegistry** — `skill_registry.py:248-253` — explicitly skipped "for MVP"
4. **CRITICAL: 35+ layer violations** — frontend imports backend internals directly (not thin client)
5. **CRITICAL: Admin endpoints without auth** — `admin_plugins.py` all endpoints only feature-flag protected
6. **HIGH: SHA-256 without salt for API keys** — `api_key_backend.py:17-23` — rainbow table vulnerable
7. **HIGH: Guard failures return "passed"** — `input_guard_mixin.py:143` — silent degradation on external service errors
8. **HIGH: SOAP/GraphQL/SSE without auth** — public endpoints expose internal structure
9. **HIGH: Symlink escape in AI workspace** — `fs_facade.py:144-147` — path resolved after concatenation
10. **HIGH: yaml.load without safe_load** — `codegen_settings.py:656` — arbitrary code execution risk
11. **MEDIUM: Workflow processors receive dict not Exchange** — `sequential_mixin.py:43-44` — cannot use route processors as-is
12. **MEDIUM: Spec hot-reload with no caching** — every workflow step re-loads spec
13. **MEDIUM: file_watch.py blocking I/O** — `os.walk()` in async processor context
14. **MEDIUM: pg_runner replay() is no-op** — no non-determinism detection
15. **MEDIUM: Inconsistent plugin lifecycle** — orders/files missing `on_register_actions` hook
16. **LOW: MetricsRegistry duplicate** — core/utils/ and infrastructure/observability/ both exist
17. **LOW: WorkflowBuilder deprecated but in use** — marked for removal after Single-Entry refactor
18. **LOW: Bulk operations without batch limits** — Redis bulk_get/set, ClickHouse insert can OOM

### Already Fixed (This Session)
- ✅ P1: async Lock in EmbeddingVectorCache
- ✅ P2: Path traversal protection in FileSink
- ✅ P3: SQL injection in AuditEventLog (bound params)
- ✅ P4: HTTP client singleton
- ✅ P5: YAML content hash caching in yaml_watcher
- ✅ P8: sqlite_doc_store SQL-level filtering
- ✅ P9: Removed duplicate core/resilience/bulkhead.py

---

## B. FILE INVENTORY

### Layer Summary

| Layer | Python Files | Key Directories |
|-------|-------------|----------------|
| core | ~450 | ai/, auth/, config/, dsl/, resilience/, security/, tenancy/, workflow/ |
| infrastructure | ~400 | database/, cache/, messaging/, sinks/, sources/, storage/, workflow/ |
| services | ~350 | ai/, execution/, plugins/, routes/, workflows/, schema_registry/ |
| entrypoints | ~200 | api/, graphql/, grpc/, mcp/, websocket/, webhook/, sse/ |
| dsl | ~300 | builders/, engine/, blueprints/, workflow/ |
| frontend | ~150 | streamlit_app/ (36+ pages) |
| extensions | ~80 | core_entities/, credit_pipeline/, osint_agent/, skb/ |
| routes | ~20 | hello_route/, echo_demo/, etc. |
| tests | 1,450 | unit/, integration/, e2e/, perf/, property/ |
| tools | ~100 | dsl_lsp/, hooks/, checks/, codemods/ |

---

## C. DOMAIN SUMMARIES

### 1. CORE (`src/backend/core/`)

**Purpose**: Domain-agnostic kernel providing protocols, interfaces, DI, resilience, security.

**Key Entities**: `AIGateway`, `AgentRegistry`, `CapabilityGate`, `CircuitBreaker`, `BreakerRegistry`, `SchedulerManager`, `TenantContext`

**Dependencies In**: None (this is the base)

**Dependencies Out**: None (domain-agnostic)

**Violations**:
- `ldap_client_factory.py:99` imports from `services/auth/` (core→services violation)
- `core/workflow/builder.py:13` imports from `infrastructure/` (core→infrastructure violation)

**Maturity**: HIGH - well-structured, capability-gated

**Issues**:
- Inconsistent `__slots__` across RouteBuilder mixins
- WorkflowBuilder marked deprecated but still used
- Core exports infrastructure implementations

---

### 2. INFRASTRUCTURE (`src/backend/infrastructure/`)

**Purpose**: External integrations - databases, caches, messaging, storage, workflows.

**Key Entities**: `DatabaseManager`, `RedisClient`, `S3ObjectStorage`, `TemporalWorkflowBackend`, `KafkaProducer`, `VaultClient`

**Dependencies In**: services/, entrypoints/

**Dependencies Out**: core/

**Maturity**: HIGH - production-grade implementations

**Issues**:
- Duplicate MetricsRegistry (`infrastructure/observability/` vs `core/utils/`)
- presidio_sanitizer.py layer violation (documented, pending Sprint 24 closure)
- Bulk operations without batch size limits
- clickhouse apply_ddl_file uses blocking read_text

**Good**:
- Path traversal protection everywhere
- Connection pooling for Redis, ClickHouse, MongoDB, HTTP
- SQL injection protection via parameterized queries

---

### 3. AI/AGENTS (`src/backend/core/ai/` + `src/backend/services/ai/`)

**Purpose**: LLM gateway, multi-agent orchestration, RAG, guardrails.

**Key Entities**: `AIGateway`, `AgentRegistry`, `SkillRegistry`, `AIPolicySpec`, `AIPolicyEnforcer`, `WorkspaceManager`

**9-Step Pipeline**: policy → capability → sanitize.input → guards.input → render → LLM → guards.output → sanitize.output → audit

**CRITICAL Issues**:
- `InProcessAgentSandbox` is DEFAULT with zero process isolation
- Tool whitelist enforced on `workflow_id` instead of actual tool
- Module whitelist explicitly skipped in SkillRegistry
- Capability check silently skips on ImportError
- Guard failures return "passed" (silent degradation)

**Security**: PARTIAL - guardrails exist but have bypass vectors

---

### 4. DSL (`src/backend/dsl/`)

**Purpose**: Declarative route/workflow definition via YAML + Python builder.

**Key Entities**: `ExecutionEngine`, `RouteBuilder`, `Pipeline`, `BaseProcessor`, `ProcessorPool`

**Maturity**: MEDIUM - powerful but complex MRO

**Critical Issues**:
- RouteBuilder has 10-mixin MRO (god class)
- `object.__setattr__` bypasses slots at line 148
- Workflow processors receive bare dict, not Exchange object
- Spec hot-reload with no caching on every step
- YAML parsed without caching (but yaml_watcher has incremental reload)
- Extended YAML files read twice (cycle check + parse)

**Good**:
- 80/20 YAML/Python split
- EIP patterns implemented
- Processor pooling
- Middleware chain

---

### 5. WORKFLOW (`src/backend/core/workflow/` + `src/backend/infrastructure/workflow/`)

**Purpose**: Durable workflow execution via Temporal/Lite/pg-runner.

**Backends**: `TemporalWorkflowBackend` (production), `LiteTemporalBackend` (dev), `PgRunnerBackend` (fallback)

**Issues**:
- pg_runner uses busy-wait polling (exponential backoff, no push)
- `replay()` is no-op - no non-determinism detection
- WorkflowBuilder deprecated but in use
- Semaphore and _active_executions tracking could get out of sync

**Good**:
- Advisory lock prevents concurrent execution
- Event replay builds state correctly
- LISTEN/NOTIFY via asyncpg for push notifications

---

### 6. FRONTEND (`src/frontend/streamlit_app/`)

**Purpose**: Operator dashboard + documentation.

**Pages**: 36+ Streamlit pages

**CRITICAL Issues**:
- 35+ direct `src.backend` imports (not thin client)
- Pages execute backend logic directly
- Admin endpoints without auth (only feature flag)

**Good**:
- Good API client abstraction (12 domain clients)
- Streamlit session state used correctly
- Secret masking in config viewer

---

### 7. EXTENSIONS (`extensions/`)

**Purpose**: Business logic plugins.

**Structure**: `plugin.toml` + `plugin.py` (BasePlugin) + services/ + domain/ + schemas/

**Issues**:
- `orders` and `files` plugins don't implement `on_register_actions`
- Still using legacy `registers_domains.py` path
- `osint_agent` has historical infrastructure imports (now fixed)

**Good**:
- Well-structured plugin manifest
- Lifecycle hooks (on_load, on_register_actions, etc.)
- Topological sort for dependency ordering

---

## D. LAYER AND DEPENDENCY ANALYSIS

### Layer Dependency Matrix

| From/To | core | infrastructure | services | dsl | entrypoints | frontend | extensions |
|---------|------|----------------|----------|-----|-------------|----------|------------|
| core | - | NO | NO | NO | NO | NO | NO |
| infrastructure | YES | - | NO | NO | NO | NO | NO |
| services | YES | YES | - | NO | NO | NO | NO |
| dsl | YES | YES | NO | - | NO | NO | NO |
| entrypoints | YES | YES | YES | NO | - | NO | NO |
| frontend | **VIOLATION** | **VIOLATION** | **VIOLATION** | NO | NO | - | NO |
| extensions | YES | **VIOLATION** | YES | NO | NO | NO | - |

### Violations Found

1. **frontend → infrastructure**: 35+ files
2. **frontend → services**: Multiple pages
3. **frontend → core**: config, logging imports
4. **extensions → infrastructure**: historical (now mostly fixed)
5. **core → services**: `ldap_client_factory.py:99`
6. **core → infrastructure**: `workflow/builder.py:13`

---

## E. TOPIC-BY-TOPIC AUDIT (22 Points)

### 1. JupyterHub / Notebooks
**Status**: PARTIAL
**Evidence**: `src/backend/services/jupyter/execution_service/` - Jupyter execution with multiple backends (E2B, Papermill, JupyterMixin)
**Problems**: No JupyterHub auth token handling visible, E2B sandbox is cloud-based
**Recommendations**: Add kernel lifecycle management, document E2B security model

### 2. Layer Independence
**Status**: CRITICAL VIOLATIONS
**Evidence**: 35+ frontend→backend imports, extensions→infrastructure historical violations
**Severity**: CRITICAL for frontend violations
**Recommendations**: Create `core.api` facade, route frontend through HTTP API clients

### 3. Performance
**Status**: ISSUES FOUND
**Evidence**:
- Workflow spec hot-reload with no caching (every step)
- file_watch.py blocking os.walk() in async context
- pg_runner busy-wait polling
- Bulk operations without batch limits
**Recommendations**: Add spec caching, wrap blocking I/O in to_thread, add batch limits

### 4. Custom Agent Policies
**Status**: CRITICAL - Tool whitelist bypassed
**Evidence**:
- `gateway_orchestrator_mixin.py:84` enforces on workflow_id not tool
- `skill_registry.py:248-253` module whitelist skipped
- InProcessAgentSandbox zero isolation
**Recommendations**: Wire AIPolicySpec tools to actual LLM tool calling, deprecate InProcessAgentSandbox

### 5. Global DI for Extensions
**Status**: GOOD
**Evidence**: `app_state_singleton`, `svcs_registry`, `svcs_container`
**Issues**: Some services use direct imports instead of DI

### 6. Duplicate Libraries
**Status**: FOUND
**Evidence**:
- `core/utils/metrics_registry.py` vs `infrastructure/observability/metrics_registry.py`
- `core/resilience/bulkhead.py` removed (P9 done)
**Recommendations**: Delete infrastructure/observability/metrics_registry.py (keep core/utils/)

### 7. Dead Code
**Status**: TRACKED
**Evidence**: 292 modules have zero internal imports (likely wired via decorators)
**Issues**: presidio_sanitizer.py shim pending Sprint 24 closure

### 8. Directory Organization
**Status**: GOOD (with exceptions)
**Good**: Layer-based structure, domain separation
**Issues**: 200+ processors in dsl/engine (domain bleed)

### 9. Import Ergonomics
**Status**: NEEDS IMPROVEMENT
**Evidence**: No `core.api` facade, deep imports required
**Recommendations**: Create `src/backend/core/api/` re-exports

### 10. Scheduler / Triggers
**Status**: GOOD
**Evidence**: APScheduler + Temporal dual backend, HITL pause/resume
**Issues**: HITL uses busy-wait polling (should use pub/sub)

### 11. Agent Workflow
**Status**: PARTIAL - Guardrails exist but bypassed
**Evidence**: 9-step enforced pipeline, but tool whitelist not enforced
**Gaps**: No per-turn token budget, prompt injection in tool results

### 12. Frontend
**Status**: VIOLATIONS FOUND
**Evidence**: 35+ direct src.backend imports
**Recommendations**: Route all through API clients, move dry-run to backend endpoint

### 13. Documentation
**Status**: GOOD
**Evidence**: 16 tutorials, 5 how-to guides, 20+ runbooks, ADR system
**Gaps**: Some tutorial path references mismatch

### 14. DSL Directory Scanning
**Status**: FIXED (P5)
**Evidence**: yaml_watcher now has SHA-256 content hash caching
**Recommendations**: None - P5 completed

### 15. CDC
**Status**: MIXED
**Evidence**: PollCDC and ListenNotifyCDC NOT Kafka-dependent; Debezium IS
**Issues**: CDCPostgresLogicalSource is scaffold only
**Recommendations**: Complete PostgreSQL logical replication

### 16. Webhooks / WebSockets / SOAP / REST / GraphQL / gRPC
**Status**: PARTIAL - Auth gaps
**Evidence**:
- REST/SOAP/GraphQL/gRPC: OK with auth
- SSE: NO auth
- WebSocket: NO auth mentioned
- SOAP: NO auth
**Recommendations**: Add auth middleware to SSE, WebSocket, SOAP

### 17. DSL Transform / Aggregate / Split / Enrich
**Status**: GOOD
**Evidence**: EIP patterns in processors/eip/
**Missing**: No explicit "enrich" pattern, no claim check, no aggregator with timeout

### 18. Middleware and DSL
**Status**: GOOD
**Evidence**: Two middleware registries, four ASGI layers, per-route overrides
**Good**: Built-in timeout, metrics, error normalization, circuit breaker per-route

### 19. External DBs and Queries
**Status**: GOOD (with issues)
**Evidence**: 95% bind params, whitelist regex for identifiers
**Issues**: sqlite_doc_store memory exhaustion FIXED (P8)
**Critical**: yaml.load without safe_load in codegen_settings.py

### 20. Configuration / Constants / Secrets
**Status**: GOOD
**Evidence**: YAML profiles, Pydantic settings, Vault integration, feature flags
**Issues**: env_secrets writes to os.environ (dev-only)

### 21. RPA / SSH / Files / Archive / OCR / S3
**Status**: PARTIAL
**Evidence**:
- FileSink path traversal PROTECTED (P2)
- S3 has _safe_key()
- Browser RPA no sandbox flags
**Issues**: fs_facade.py symlink escape (HIGH)

### 22. Caching / SSE
**Status**: GOOD (caching), PARTIAL (SSE)
**Evidence**: 3-tier cache (Redis→Memory→Disk), semantic cache for RAG
**SSE Issues**: No auth, PII streaming best-effort

---

## F. DSL COVERAGE MAP

| Functionality | Runtime | DSL | Extensions | Missing |
|---------------|---------|-----|------------|---------|
| Route definition | ✅ | ✅ | ✅ | - |
| HTTP calls | ✅ | ✅ | ✅ | - |
| Database queries | ✅ | ✅ | ✅ | - |
| Message publishing | ✅ | ✅ | ✅ | - |
| File operations | ✅ | ✅ | ✅ | - |
| AI/LLM calls | ✅ | ✅ | ✅ | - |
| RAG pipeline | ✅ | ✅ | ✅ | - |
| CDC (Poll) | ✅ | ✅ | ✅ | - |
| Workflow (Temporal) | ✅ | ✅ | ✅ | - |
| HITL | ✅ | ✅ | ✅ | - |
| Saga | ✅ | ✅ | ✅ | - |
| Subworkflow | ✅ | ✅ | ✅ | - |
| Browser RPA | ✅ | ⚠️ | ⚠️ | Full DSL |
| SSH/RPA | ⚠️ | ❌ | ❌ | DSL wrapper |

---

## G. DUPLICATE / SMELL / DEAD CODE REPORT

| File/Symbol | Smell | Severity | Proposed Fix |
|-------------|-------|----------|--------------|
| `infrastructure/observability/metrics_registry.py` | Duplicate | MEDIUM | Delete, keep `core/utils/metrics_registry.py` |
| `src/backend/services/ai/agent_sandbox.py:85` | Zero-isolation sandbox | CRITICAL | Deprecate InProcessAgentSandbox, make ProcessPool/E2B default |
| `src/backend/core/ai/skill_registry.py:248-253` | Module whitelist bypass | CRITICAL | Implement whitelist check |
| `src/backend/core/ai/gateway_orchestrator_mixin.py:84` | Tool whitelist wrong target | CRITICAL | Enforce on actual tool invoked |
| `tools/codegen_settings.py:656` | yaml.load without safe_load | HIGH | Use yaml.safe_load |
| `src/backend/core/ai/fs_facade.py:144-147` | Symlink escape race | HIGH | Resolve path before concatenation |
| `src/backend/dsl/engine/processors/file_watch.py:77-103` | Blocking I/O in async | MEDIUM | Wrap in asyncio.to_thread |
| `src/backend/dsl/executor/sequential_mixin.py:43-44` | Workflow gets dict not Exchange | MEDIUM | TODO comment acknowledged |
| `src/backend/infrastructure/workflow/pg_runner_backend.py:217` | replay() is no-op | MEDIUM | Document limitation or implement |
| `src/backend/dsl/workflow/builder.py:1-3` | Deprecated but in use | LOW | Complete Single-Entry refactor |

---

## H. DEPENDENCIES REVIEW

| Dependency | Purpose | Overlaps | Keep/Remove | Notes |
|------------|---------|----------|-------------|-------|
| temporalio | Workflow engine | - | KEEP | Production default |
| fastapi | Web framework | starlette | KEEP | |
| pydantic | Data validation | - | KEEP | |
| sqlalchemy | ORM | - | KEEP | |
| redis | Cache/queue | | KEEP | |
| httpx | HTTP client | requests | KEEP | Async-first |
| grpcio | gRPC | - | KEEP | |
| strawberry-graphql | GraphQL | - | KEEP | |
| zeep | SOAP | - | KEEP | |
| playwright | Browser automation | selenium | KEEP | Primary RPA |
| presidio-analyzer | PII detection | - | KEEP | |
| langgraph | Agent graphs | - | KEEP | |
| langfuse | LLM observability | - | KEEP | |

**No duplicate abstractions found** - each library has distinct purpose.

---

## I. DOCUMENTATION REVIEW

**Good**:
- Russian policy followed in tutorials
- Core protocols well-documented
- DSL engine has docstrings
- ADR system (30+ records)

**Gaps**:
- Some Streamlit pages lack docstrings
- Processor docstrings inconsistent
- Outdated comments not removed
- No docstring linter in CI

---

## J. REFACTORING ROADMAP

### Horizon 1: Quick Wins (1–3 days) — COMPLETED

| ID | Status | Finding |
|----|--------|---------|
| P1 | ✅ DONE | Fix async Lock in EmbeddingVectorCache |
| P2 | ✅ DONE | Add path traversal protection to FileSink |
| P3 | ✅ DONE | Fix SQL injection in AuditEventLog |
| P4 | ✅ DONE | Add HTTP client singleton |
| P5 | ✅ DONE | Add YAML content hashing to yaml_watcher |
| P8 | ✅ DONE | sqlite_doc_store SQL-level filtering |
| P9 | ✅ DONE | Remove duplicate bulkhead.py |

### Horizon 2: Stabilization (1–3 weeks)

| ID | Priority | Description | Risk | Breaking |
|----|----------|-------------|------|----------|
| P10 | HIGH | Add auth to admin endpoints | LOW | NO |
| P11 | HIGH | Add auth to SOAP/GraphQL/SSE | MEDIUM | NO |
| P12 | HIGH | Fix tool whitelist enforcement | MEDIUM | NO |
| P13 | HIGH | Add timeout to LLM Guard scan | LOW | NO |
| P14 | MEDIUM | Add batch limits to bulk operations | LOW | NO |
| P15 | MEDIUM | Wrap blocking I/O in file_watch | LOW | NO |
| P16 | MEDIUM | Fix fs_facade symlink race | MEDIUM | NO |
| P17 | MEDIUM | yaml.safe_load in codegen_settings | LOW | NO |
| P18 | MEDIUM | Delete infrastructure/metrics_registry | LOW | NO |
| P6 | HIGH | Fix frontend layer violations | HIGH | YES |
| P7 | HIGH | Fix extension layer violations | HIGH | YES |

### Horizon 3: Platform Evolution (1–3 months)

| ID | Description | Risk | Breaking |
|----|-------------|------|----------|
| P19 | Deprecate InProcessAgentSandbox | HIGH | YES |
| P20 | Add token budget enforcement | MEDIUM | NO |
| P21 | Create core.api facade | MEDIUM | YES |
| P22 | Complete CDC PostgreSQL implementation | MEDIUM | NO |
| P23 | Replace HITL busy-wait with pub/sub | MEDIUM | NO |
| P24 | Wire AIPolicySpec tools enforcement | MEDIUM | NO |

---

## K. PROPOSED TARGET ARCHITECTURE

### Target Package Layout

```
src/backend/
├── core/
│   ├── api/                 # NEW: Public re-exports for extensions
│   │   ├── __init__.py
│   │   ├── ai.py           # AIGateway, AgentRegistry
│   │   ├── auth.py         # AuthFacade
│   │   ├── workflow.py     # WorkflowManager
│   │   └── config.py       # Settings
│   ├── protocols.py         # Keep existing
│   ├── interfaces/          # Keep existing
│   ├── resilience/          # Keep existing
│   └── security/            # Keep existing
├── infrastructure/          # Internal implementations
├── services/               # Internal services
├── dsl/                    # Keep as-is
├── entrypoints/             # Keep as-is
└── frontend/               # Must use core.api only

extensions/
└── <name>/
    └── plugin.py           # Can import from core.api only
```

---

## L. IMPLEMENTATION BACKLOG

| ID | Title | Description | Files Impacted | Priority | Effort | Risk |
|----|-------|-------------|----------------|----------|--------|------|
| P1 | Fix async Lock | EmbeddingVectorCache asyncio.Lock | embedding_cache.py | CRITICAL | 1h | LOW |
| P2 | Path traversal | FileSink _safe_path | file_sink.py | CRITICAL | 2h | LOW |
| P3 | SQL injection | AuditEventLog bound params | event_log.py | CRITICAL | 2h | LOW |
| P4 | HTTP singleton | get_http_client_dependency | factory.py | CRITICAL | 4h | LOW |
| P5 | YAML caching | yaml_watcher hash cache | yaml_watcher.py | CRITICAL | 1d | MEDIUM |
| P6 | Frontend violations | Route through API clients | 35+ pages | HIGH | 1w | HIGH |
| P7 | Extension violations | Create facade + migrate | extensions/* | HIGH | 1w | HIGH |
| P8 | SQL filtering | sqlite_doc_store streaming | sqlite_doc_store.py | HIGH | 4h | MEDIUM |
| P9 | Duplicate bulkhead | Remove core/resilience/bulkhead.py | bulkhead.py | MEDIUM | 1h | LOW |
| P10 | Admin auth | Add require_auth to admin endpoints | admin_plugins.py | HIGH | 2h | LOW |
| P11 | SOAP/GraphQL/SSE auth | Add auth middleware | soap_handler.py, etc. | HIGH | 4h | MEDIUM |
| P12 | Tool whitelist | Enforce on actual tool | gateway_orchestrator_mixin.py | HIGH | 2d | MEDIUM |
| P13 | LLM Guard timeout | Add timeout to scan | input_guard_mixin.py | MEDIUM | 1h | LOW |
| P14 | Bulk batch limits | Add max_batch to bulk ops | redis/cache_mixin.py | MEDIUM | 2h | LOW |
| P15 | file_watch blocking | Wrap os.walk in to_thread | file_watch.py | MEDIUM | 2h | LOW |
| P16 | fs_facade symlink | Resolve before concat | fs_facade.py | HIGH | 2h | MEDIUM |
| P17 | yaml.safe_load | Replace yaml.load | codegen_settings.py | HIGH | 10min | LOW |
| P18 | Delete metrics duplicate | Remove infra version | metrics_registry.py | MEDIUM | 1h | LOW |

---

## M. FINAL VERDICT

| Dimension | Score | Notes |
|-----------|-------|-------|
| **Architectural Maturity** | 7/10 | Strong core, but complexity in MRO and processor proliferation |
| **Extensibility** | 6/10 | Good plugin system, layer violations in extensions/frontend |
| **Production Readiness** | 7/10 | Core is production-ready, some security gaps in AI/agents |
| **DSL Completeness** | 8/10 | Comprehensive, YAML caching fixed (P5) |
| **Agent Safety** | 4/10 | Guardrails exist but bypassed, zero-isolation default sandbox |
| **Docs Maturity** | 8/10 | Good tutorials, runbooks, ADRs |
| **Maintainability** | 6/10 | Technical debt in AI sandbox, tool enforcement, frontend violations |

### What is Already Good (Do Not Break)

1. Protocol-based interchangeability (PEP 544)
2. Capability-gated features throughout
3. Resilience patterns (CB, retry, bulkhead, rate-limit)
4. Multi-backend support (Temporal, Lite, pg-runner)
5. DSL/YAML declarative approach
6. Connection pooling for all external clients
7. Path traversal protection in file operations
8. SQL injection protection via parameterized queries

### What Must Be Isolated Before Scaling

1. **Agent sandbox** — InProcessAgentSandbox must be deprecated
2. **Tool policy enforcement** — must be wired to actual tool invocation
3. **Frontend layer violations** — 35+ files need facade refactor
4. **Admin endpoints** — require auth, not just feature flag

### What is Dangerous to Ship to Prod Now

1. **Zero-isolation sandbox as default** — any agent compromise = full process access
2. **Tool whitelist bypass** — agents can call any tool regardless of policy
3. **yaml.load without safe_load** — code execution risk in tools
4. **Symlink race in workspace** — arbitrary filesystem write
5. **Guard failures return "passed"** — silent security bypass

### What Can Become Stable Public API for Extensions

1. `core.api` - Facade for AI, Auth, Workflow, Config
2. `BasePlugin` lifecycle hooks
3. `ProcessorRegistryProtocol` for DSL processors
4. `ActionRegistryProtocol` for actions
5. `CapabilityGate` for capability declaration

---

**End of Audit Report**
