# Milestone 2 — Infrastructure DSL Ecosystem

## Goal
Comprehensive infrastructure layer with: healthcheck coverage, DSL processors over facades for all infra categories, async/connection-pool performance, complete config (.env + .yml), CDC/dir-scan/external-DB DSL.

## Architecture (verify existing)
- 94 facade providers in `infrastructure_facade.py` (already isolated)
- 100+ DSL processors in `src/backend/dsl/engine/processors/`
- 15+ connection pools in `infrastructure/`

## Phases (sequential, each with verification)

### Phase 1: Healthcheck Audit (1-2 days)
- **Goal**: Verify healthcheck exists for ALL infra components
- Check: `health_aggregator.py`, `monitoring/health_check.py`, `transport/health.py`
- **Gap analysis**: which components lack healthcheck?
- Add missing health probes for: ClickHouse, MongoDB, S3/MinIO, Kafka, RabbitMQ, NATS
- Tests: `tests/unit/infrastructure/monitoring/test_health_aggregator.py`

### Phase 2: Facade → DSL (2-3 days)
- **Goal**: Add DSL processors that call facade providers
- New processors (use `call_function('module:fn')` pattern):
  - `facade_get_health` — call any facade provider from routes
  - `facade_invoke` — generic facade invocation
  - `infra_s3_upload` / `infra_s3_download` (use facade S3 providers)
  - `infra_redis_get` / `infra_redis_set` (use facade Redis providers)
  - `infra_db_query` (use facade DB providers)
  - `infra_log_write` (use facade logger providers)
- Pattern: each processor lazy-imports facade provider, validates input, calls provider, returns result

### Phase 3: Gap-Fill DSL (3-4 days)
**Existing coverage**:
- ✅ S3: `storage/s3.py` (5 processors)
- ✅ DB: `db_crud.py`, `db_call_procedure.py`, `db_query_external.py`
- ✅ File: `file_watch.py`, `fs_directory_scan.py`, `scan_file.py`
- ✅ CDC: `cdc_capture.py`, `cdc_transform.py`
- ✅ Streaming: 4 files in `streaming/`
- ✅ Notify: `apprise_notify.py`

**Potential gaps**:
- ClickHouse processor (only `audit_clickhouse.py` exists, not general)
- MongoDB processor (no direct)
- Graylog/structured logging DSL (no DSL, only Python)
- Queue DSL (Kafka/RabbitMQ) — check existing

For each gap: create processor or document why absent.

### Phase 4: Performance (2-3 days)
- **Audit async-first compliance**:
  - All DB calls via `asyncpg` / `motor` / async drivers
  - No `requests` in async paths (use `httpx`)
  - No `psycopg2` sync in async context
- **Connection pools**:
  - Verify pool sizes in `config_profiles/base.yml`
  - Add pool warmup where missing
- **Acceleration libs**:
  - `orjson` for JSON serialization
  - `uvloop` for asyncio loop (if not enabled)
  - `httpx` HTTP/2
- **Benchmark suite** to track regressions

### Phase 5: Config Completeness (1-2 days)
- Audit `.env.example` (139 lines) vs `config_profiles/*.yml`
- Audit actual `Settings` classes in `core/config/`
- Add missing env vars
- Add YAML defaults
- Test: load each profile, check no `MissingEnvVarError`

## Tech Stack
- Python 3.14+
- asyncpg, motor, aioboto3, aio-pika, aiokafka
- httpx (HTTP), orjson (JSON), uvloop (loop)
- pytest, pytest-asyncio, pytest-mock
- Pydantic v2

## Constraints (project rules, binding)
- 80% DSL / 20% Python via `call_function`
- Async-first, no blocking I/O in async context
- Type hints everywhere (Python 3.14+ syntax)
- Capability-checked facades for cross-layer
- D5 binding: zero new test regressions (45/2736 baseline)
- Ponytail: minimum working code, no premature abstraction
- No secrets in code, only Vault

## Risks
- Healthcheck for every component = many new probes → test maintenance
- DSL coverage audit may reveal existing patterns we should consolidate (not duplicate)
- Performance changes may have side effects on existing tests
- Config completeness = touching many files

## Verification
- After each phase: `pytest tests/ --tb=no -q` — must not increase failure count
- AST check: 0 new core→infra imports
- DSL processor tests: each new processor has at least 3 tests

## Out of scope (explicit)
- Frontend → backend import cleanup (33 files)
- credit_pipeline scaffolding
- Frontend pages with direct imports
- Other than listed 7 user directions

## Estimated effort
- Phase 1: 1-2 days
- Phase 2: 2-3 days
- Phase 3: 3-4 days
- Phase 4: 2-3 days
- Phase 5: 1-2 days
**Total: 9-14 days** (sequential with verification per phase)